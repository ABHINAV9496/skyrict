"""ERP tenant-scoped sequences and the core audit hash chain.

Adds two tenant-scoped tables to the core schema:

- ``erp_sequences`` — a lightweight per-tenant monotonic counter store used by
  ERP document numbering (invoice / payment / quote numbers). Each counter is
  a row keyed by ``(tenant_id, entity)``; services claim the next number with a
  row-locking ``UPDATE ... SET current_value = current_value + 1 RETURNING``,
  so consecutive numbers are race-safe and never reused.

- ``core_audit_logs`` — a tamper-evident, append-only audit trail for core
  (ERP) actions. It mirrors identity's ``audit_logs`` (same physical database,
  same contract): a BEFORE INSERT trigger builds a SHA-256 hash chain over the
  previous hash plus the immutable row fields, and a second trigger forbids
  direct UPDATE / DELETE. The hash lookup is subject to the same RLS filter as
  the inserting user, so each tenant's chain is self-contained. The sha256
  ``digest`` comes from the ``pgcrypto`` extension that identity's 0001 owns;
  core enables it ``IF NOT EXISTS`` here so the chain is self-contained when
  core's own chain is migrated alone (tests).

Also seeds the six ERP permission keys defined in the HR & Payroll design doc
(``docs/design/hr-payroll.md``) into ``core_permissions`` — the platform-fixed
catalog that identity's ``permissions`` mirrors and role grants reference
(``erp.hr.*`` and ``erp.payroll.*``).

Revision ID: 0010
Revises: 0006
Create Date: 2026-08-13
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0006"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# ERP permission keys (design doc hr-payroll.md; platform-fixed catalog)
# ---------------------------------------------------------------------------
# Literal values only (fixed tuple below) so offline SQL generation works.
_PERMISSION_KEYS = (
    (
        "erp.hr.read",
        "View departments, employees, leave requests, balances, and movements",
    ),
    (
        "erp.hr.write",
        "Create/edit departments, employees, and leave requests; adjust balances and accrue leave",
    ),
    ("erp.hr.approve", "Approve, reject, or cancel leave requests"),
    ("erp.payroll.read", "View compensation records, payroll runs, entries, and payroll settings"),
    (
        "erp.payroll.write",
        "Create payroll runs, compute payroll, edit draft entries, and update settings",
    ),
    ("erp.payroll.approve", "Approve, void, or mark a payroll run as paid"),
)

_TENANT_SCOPED_TABLES = (
    "erp_sequences",
    "core_audit_logs",
)


# ---------------------------------------------------------------------------
# Schema helpers (shared idiom across the core chain)
# ---------------------------------------------------------------------------
def _tenant_scoped_pk() -> list[Any]:
    """Composite (tenant_id, id) PK so no generated PK column leaks.

    ``tenant_id`` is the PK's leading column, so PK lookups are already
    tenant-partitioned without a separate index.
    """
    return [
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    ]


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def _updated_at() -> sa.Column[Any]:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


# ---------------------------------------------------------------------------
# Row-level security helpers (idempotent)
# ---------------------------------------------------------------------------
def _create_rls_policy(table: str) -> None:
    """Enable RLS and create the tenant-isolation policy for a tenant table."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table} ON public.{table} "
        "USING (tenant_id = public.current_tenant_id()) "
        "WITH CHECK (tenant_id = public.current_tenant_id())"
    )


def _drop_rls_policy(table: str) -> None:
    """Disable RLS and drop the tenant-isolation policy for a tenant table."""
    op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON public.{table}")


# ---------------------------------------------------------------------------
# RLS helper for the ``app.current_tenant_id`` GUC (idempotent)
# ---------------------------------------------------------------------------
def _ensure_current_tenant_id() -> None:
    """
    Pins the current-tenant-id function that RLS policies reference.

    Not every migration needs to create this, but doing so is harmless and
    keeps the SQL for migration scripts self-contained.
    """
    op.execute(
        "CREATE OR REPLACE FUNCTION public.current_tenant_id() RETURNS uuid "
        "LANGUAGE sql STABLE AS $$ "
        "SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid $$"
    )


def upgrade() -> None:
    # Identity 0001 owns ``pgcrypto`` in the shared database; ``IF NOT EXISTS``
    # makes core's audit chain self-contained when core's chain is migrated
    # alone (integration tests). Core's downgrade must NOT drop the extension.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # --- erp_sequences: per-tenant monotonic document counters -----------
    op.create_table(
        "erp_sequences",
        *_tenant_scoped_pk(),
        sa.Column("entity", sa.String(64), nullable=False),
        sa.Column(
            "current_value",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("tenant_id", "entity", name="uq_erp_sequences_tenant_entity"),
    )

    # --- core_audit_logs: tamper-evident append-only audit trail ----------
    # Column-for-column mirror of identity's ``audit_logs``. ``actor_user_id``
    # is a plain UUID with NO FK: it references identity users in the same
    # shared database but is owned by another service's schema/RLS; validated
    # via ports (same idiom as 0005's actor columns).
    op.create_table(
        "core_audit_logs",
        *_tenant_scoped_pk(),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=True),
        _created_at(),
    )
    op.create_index(
        "ix_core_audit_logs_tenant_created",
        "core_audit_logs",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_core_audit_logs_tenant_action",
        "core_audit_logs",
        ["tenant_id", "action"],
    )

    # --- Row-level security -----------------------------------------------
    _ensure_current_tenant_id()
    for table in _TENANT_SCOPED_TABLES:
        _create_rls_policy(table)

    # --- Audit tamper-evidence: hash chain + append-only -------------------
    # Mirrors identity's ``audit_logs`` triggers (same contract). The previous
    # hash is looked up under the invoking user's RLS, so each tenant's chain
    # is self-contained and tamper-evident.
    op.execute(
        """
        CREATE FUNCTION public.core_audit_logs_set_hash() RETURNS trigger AS $$
        DECLARE
            prev char(64);
        BEGIN
            SELECT hash INTO prev FROM public.core_audit_logs
            ORDER BY created_at DESC, id DESC LIMIT 1;
            NEW.created_at := COALESCE(NEW.created_at, now());
            NEW.prev_hash := COALESCE(prev, repeat('0', 64));
            NEW.hash := encode(digest(
                NEW.prev_hash::text
                || NEW.action::text
                || NEW.target::text
                || COALESCE(NEW.actor_user_id::text, '')
                || NEW.tenant_id::text
                || NEW.created_at::text,
                'sha256'
            ), 'hex');
            RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER core_audit_logs_hash_chain BEFORE INSERT ON public.core_audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION public.core_audit_logs_set_hash()"
    )

    op.execute(
        """
        CREATE FUNCTION public.core_audit_logs_append_only() RETURNS trigger AS $$
        BEGIN
            -- Referential-integrity writes (FK CASCADE / SET NULL) fire at
            -- trigger depth >= 2; allow those. Direct UPDATE/DELETE against
            -- the log (depth 1) is rejected: the log is append-only.
            IF pg_trigger_depth() > 1 THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                ELSE
                    RETURN NEW;
                END IF;
            END IF;
            RAISE EXCEPTION 'core_audit_logs is append-only; UPDATE/DELETE forbidden';
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER core_audit_logs_append_only BEFORE UPDATE OR DELETE ON public.core_audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION public.core_audit_logs_append_only()"
    )

    # --- Seed the ERP permission catalog ------------------------------------
    # Literal values only (fixed tuple above) so offline SQL generation works.
    permission_rows = ", ".join(
        f"('{key}', '{description}')" for key, description in _PERMISSION_KEYS
    )
    op.execute(
        # ``permission_rows`` is built solely from the compile-time literal
        # ``_PERMISSION_KEYS`` above — no user input, so this f-string SQL
        # is not an injection vector.
        "INSERT INTO core_permissions (key, description) VALUES "
        f"{permission_rows} ON CONFLICT (key) DO NOTHING"  # nosec B608
    )


def downgrade() -> None:
    # 1) drop the audit triggers
    op.execute("DROP TRIGGER IF EXISTS core_audit_logs_hash_chain ON public.core_audit_logs")
    op.execute("DROP TRIGGER IF EXISTS core_audit_logs_append_only ON public.core_audit_logs")

    # 2) drop the audit trigger functions
    op.execute("DROP FUNCTION IF EXISTS public.core_audit_logs_set_hash()")
    op.execute("DROP FUNCTION IF EXISTS public.core_audit_logs_append_only()")

    # 3) drop RLS policies and disable RLS on the tenant tables
    for table in _TENANT_SCOPED_TABLES:
        _drop_rls_policy(table)

    # 4) drop the tenant-scoped tables
    op.drop_table("core_audit_logs")
    op.drop_table("erp_sequences")

    # 5) remove the seeded ERP permissions (identity's ``permissions`` mirror
    #    and any grants remain untouched; grants to a missing key are inert)
    keys = ", ".join(f"'{key}'" for key, _ in _PERMISSION_KEYS)
    op.execute(
        # ``keys`` is built solely from the compile-time literal
        # ``_PERMISSION_KEYS`` above — no user input, so this f-string SQL
        # is not an injection vector.
        f"DELETE FROM core_permissions WHERE key IN ({keys})"  # nosec B608
    )
