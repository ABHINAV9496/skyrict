"""AI foundation tables - query log, suggestions, anomalies, audit log,
agent registry (SKY-57 / AI-INFRA-001).

Creates the five tables the AI agent owns in the shared ``skyrict_identity``
database:

- ``ai_query_log`` - append-only log of every NL query (spec §2.6)
- ``ai_suggestions`` - restock suggestions + approval workflow, including the
  PARTIAL UNIQUE index that caps one pending suggestion per tenant/product/
  warehouse (spec §3.6)
- ``ai_anomalies`` - detected anomalies + review workflow (spec §4.7)
- ``ai_audit_log`` - append-only AI audit trail (spec §5.3, Appendix B
  vocabulary enforced at the application layer by ``AuditService``)
- ``agent_registry`` - GLOBAL catalog of agent modules/graphs (no tenant_id,
  no RLS)

Tenant-scoped tables use the repo-wide composite ``(tenant_id, id)`` primary
key and row-level security against ``public.current_tenant_id()`` (identity
owns both - they must exist before this chain runs). Cross-service UUID
columns (product/warehouse/user references) deliberately carry NO FK: those
tables are owned by other services' migration chains; integrity is validated
through service ports (same idiom as ``core_audit_logs.actor_user_id``).

Revision ID: 0001
Revises:
Create Date: 2026-08-24
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Tenant-scoped tables get RLS; agent_registry is global platform data.
_TENANT_SCOPED_TABLES = (
    "ai_query_log",
    "ai_suggestions",
    "ai_anomalies",
    "ai_audit_log",
)


# ---------------------------------------------------------------------------
# Schema helpers (shared idiom across the core/ai-agent chains)
# ---------------------------------------------------------------------------
def _tenant_scoped_pk(fk: bool) -> list[Any]:
    """Composite (tenant_id, id) PK so no generated PK column leaks.

    ``tenant_id`` is the PK's leading column, so PK lookups are already
    tenant-partitioned without a separate index. With ``fk=True`` the leading
    column also cascades from identity's ``tenants`` (repo convention).
    """
    columns: list[Any] = [
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        )
        if fk
        else sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    ]
    return columns


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


def _ensure_current_tenant_id() -> None:
    """
    Pins the current-tenant-id function that RLS policies reference.

    Identity owns this function in the shared database; creating it here
    ``IF NOT EXISTS`` keeps the AI chain self-contained when migrated alone
    (integration tests on a scratch database after identity's chain).
    """
    op.execute(
        "CREATE OR REPLACE FUNCTION public.current_tenant_id() RETURNS uuid "
        "LANGUAGE sql STABLE AS $$ "
        "SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid $$"
    )


def upgrade() -> None:
    # --- agent_registry: global agent catalog (no tenant scoping, no RLS) --
    op.create_table(
        "agent_registry",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("module", sa.String(200), nullable=False),
        sa.Column("graph_id", sa.String(100), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("name", name="uq_agent_registry_name"),
    )

    # --- ai_query_log: append-only NL query log (spec §2.6) -----------------
    op.create_table(
        "ai_query_log",
        *_tenant_scoped_pk(fk=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("parsed_intent", postgresql.JSONB(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("model_used", sa.String(50), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        _created_at(),
    )

    # --- ai_suggestions: restock workflow (spec §3.6) -----------------------
    op.create_table(
        "ai_suggestions",
        *_tenant_scoped_pk(fk=True),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("current_stock", sa.Numeric(18, 4), nullable=False),
        sa.Column("reorder_point", sa.Numeric(18, 4), nullable=False),
        sa.Column("suggested_qty", sa.Numeric(18, 4), nullable=False),
        sa.Column("estimated_cost", sa.Numeric(18, 4), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        _created_at(),
        _updated_at(),
        # Unnamed in the spec DDL; named here per repo convention.
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name="ck_ai_suggestions_status",
        ),
        sa.CheckConstraint(
            "suggested_qty > 0",
            name="ck_ai_suggestions_suggested_qty_positive",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_ai_suggestions_confidence_range",
        ),
    )

    # --- ai_anomalies: detection + review workflow (spec §4.7) --------------
    op.create_table(
        "ai_anomalies",
        *_tenant_scoped_pk(fk=True),
        sa.Column("anomaly_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("affected_product_id", sa.Uuid(), nullable=True),
        sa.Column("affected_warehouse_id", sa.Uuid(), nullable=True),
        sa.Column("related_movement_ids", postgresql.ARRAY(sa.Uuid()), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_ai_anomalies_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed', 'escalated')",
            name="ck_ai_anomalies_status",
        ),
    )

    # --- ai_audit_log: append-only AI audit trail (spec §5.3) ----------------
    op.create_table(
        "ai_audit_log",
        *_tenant_scoped_pk(fk=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=True),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        _created_at(),
    )

    # --- Indexes (spec §2.6 / §3.6 / §4.7 names preserved) ------------------
    op.create_index(
        "idx_ai_query_log_tenant",
        "ai_query_log",
        ["tenant_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_ai_suggestions_tenant_status",
        "ai_suggestions",
        ["tenant_id", "status", sa.text("created_at DESC")],
    )
    # Only ONE pending suggestion per tenant+product+warehouse; decided rows
    # are exempt through the partial WHERE clause.
    op.create_index(
        "idx_ai_suggestions_pending_unique",
        "ai_suggestions",
        ["tenant_id", "product_id", "warehouse_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "idx_ai_anomalies_tenant_status",
        "ai_anomalies",
        ["tenant_id", "status", "severity", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_ai_audit_log_tenant_created",
        "ai_audit_log",
        ["tenant_id", sa.text("created_at DESC")],
    )

    # --- Row-level security ---------------------------------------------------
    _ensure_current_tenant_id()
    for table in _TENANT_SCOPED_TABLES:
        _create_rls_policy(table)


def downgrade() -> None:
    # 1) drop RLS policies and disable RLS on the tenant tables
    for table in _TENANT_SCOPED_TABLES:
        _drop_rls_policy(table)

    # 2) drop the tables (indexes and constraints go with them); the global
    #    catalog last so nothing references it mid-unwind.
    op.drop_table("ai_query_log")
    op.drop_table("ai_suggestions")
    op.drop_table("ai_anomalies")
    op.drop_table("ai_audit_log")
    op.drop_table("agent_registry")
