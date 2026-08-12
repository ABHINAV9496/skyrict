"""initial schema: erp_currencies, core_permissions, core_roles, core_user_roles

- Idempotent ``public.current_tenant_id()``: identity's 0001 already creates
  this function with a plain ``CREATE FUNCTION``; core re-creates it with
  ``CREATE OR REPLACE`` so the two services can migrate the shared database
  in any order.
- ``erp_currencies`` — global ISO 4217 reference catalog (no RLS), seeded.
- ``core_permissions`` — global platform-fixed ERP catalog (no RLS), seeded.
- ``core_roles`` — tenant-scoped, Row-Level Security via
  ``public.current_tenant_id()``, COMPOSITE PRIMARY KEY ``(tenant_id, id)``.
- ``core_user_roles`` — tenant-scoped, RLS, COMPOSITE FOREIGN KEY
  ``(tenant_id, role_id) -> core_roles(tenant_id, id)``.

COMPOSITE-FK RLS CONVENTION (ERP feature tables MUST follow this):
  a tenant-scoped table declares ``tenant_id`` as BOTH its RLS column and a
  member of its primary key, and references its parent with a composite FK
  that includes ``tenant_id``. Then a child row can only ever point at a
  parent in the SAME tenant — referential integrity agrees with RLS and the
  cross-tenant reference hole is closed at the constraint level, not just
  filtered at query time.

DEPENDS ON identity's migration 0001_initial_schema: core_roles and
core_user_roles FK ``tenant_id -> tenants(id)``, so identity must be migrated
first (``make setup`` runs identity then core). The tenants table has a
permissive SELECT policy (``tenants_readable``) so routing middleware can
resolve slugs before any request tenant context exists.

Migration bookkeeping is isolated under ``alembic_version_core`` (env.py) so
identity and core never clobber each other's version in the shared database.

Revision ID: 0001
Revises:
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_TENANT_SCOPED_TABLES = ("core_roles", "core_user_roles")

# ---------------------------------------------------------------------------
# Currency catalog (global, seeded — ISO 4217)
# ---------------------------------------------------------------------------
CURRENCY_CATALOG: tuple[tuple[str, str, str, str], ...] = (
    ("USD", "US Dollar", "$", "840"),
    ("EUR", "Euro", "€", "978"),
    ("GBP", "British Pound", "£", "826"),
    ("JPY", "Japanese Yen", "¥", "392"),
    ("CHF", "Swiss Franc", "Fr", "756"),
    ("CAD", "Canadian Dollar", "$", "124"),
    ("AUD", "Australian Dollar", "$", "036"),
    ("NZD", "New Zealand Dollar", "$", "554"),
    ("INR", "Indian Rupee", "₹", "356"),
    ("CNY", "Chinese Yuan", "¥", "156"),
    ("SGD", "Singapore Dollar", "S$", "702"),
    ("HKD", "Hong Kong Dollar", "HK$", "344"),
    ("SEK", "Swedish Krona", "kr", "752"),
    ("NOK", "Norwegian Krone", "kr", "578"),
    ("DKK", "Danish Krone", "kr", "208"),
    ("PLN", "Polish Zloty", "zł", "985"),
    ("BRL", "Brazilian Real", "R$", "986"),
    ("MXN", "Mexican Peso", "$", "484"),
    ("ZAR", "South African Rand", "R", "710"),
    ("AED", "UAE Dirham", "د.إ", "784"),
)

# ---------------------------------------------------------------------------
# ERP permission catalog (global, seeded — must match core/core/permissions.py)
# ---------------------------------------------------------------------------
PERMISSION_CATALOG: tuple[tuple[str, str], ...] = (
    ("erp.inventory.read", "View inventory records"),
    ("erp.inventory.write", "Create and update inventory records"),
    ("erp.inventory.adjust", "Record inventory adjustments"),
    ("erp.inventory.adjust.approve", "Approve inventory adjustments"),
    ("erp.purchase.read", "View purchase orders"),
    ("erp.purchase.write", "Create and update purchase orders"),
    ("erp.purchase.approve", "Approve purchase orders"),
    ("erp.sales.read", "View sales orders"),
    ("erp.sales.write", "Create and update sales orders"),
    ("erp.invoice.read", "View invoices"),
    ("erp.invoice.write", "Create and update invoices"),
    ("erp.invoice.approve", "Approve invoices"),
)


def upgrade() -> None:
    # --- Row-Level Security helper (idempotent — shared with identity) ---
    op.execute(
        "CREATE OR REPLACE FUNCTION public.current_tenant_id() RETURNS uuid "
        "LANGUAGE sql STABLE AS $$ "
        "SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid $$"
    )

    # --- erp_currencies (global reference, no RLS) ---
    op.create_table(
        "erp_currencies",
        sa.Column("code", sa.String(3), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(8), nullable=False, server_default=sa.text("''")),
        sa.Column("numeric", sa.String(3), nullable=False, server_default=sa.text("''")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- core_permissions (global reference, no RLS) ---
    op.create_table(
        "core_permissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255), nullable=False, server_default=sa.text("''")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("key", name="uq_core_permissions_key"),
    )
    op.create_index("ix_core_permissions_key", "core_permissions", ["key"], unique=True)

    # --- core_roles (tenant-scoped, composite PK, RLS) ---
    op.create_table(
        "core_roles",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("is_system_role", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_core_roles_tenant_name"),
    )

    # --- core_user_roles (tenant-scoped, composite FK to core_roles, RLS) ---
    op.create_table(
        "core_user_roles",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Composite-FK convention: the grant can only ever reference a role in
        # the SAME tenant — referential integrity agrees with RLS.
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["core_roles.tenant_id", "core_roles.id"],
            ondelete="CASCADE",
            name="fk_core_user_roles_role_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "role_id", "scope_id", name="uq_core_user_roles_scope"
        ),
    )
    op.create_index("ix_core_user_roles_user_id", "core_user_roles", ["user_id"])
    op.create_index("ix_core_user_roles_role_id", "core_user_roles", ["role_id"])

    # --- Row-Level Security policies ---
    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON public.{table} "
            "USING (tenant_id = public.current_tenant_id()) "
            "WITH CHECK (tenant_id = public.current_tenant_id())"
        )

    # --- Seed reference data (literal values only — offline SQL generation) ---
    currency_rows = ", ".join(
        f"('{code}', '{name}', '{symbol}', '{numeric}')"
        for code, name, symbol, numeric in CURRENCY_CATALOG
    )
    op.execute(
        # ``currency_rows`` is built solely from the compile-time literal
        # ``CURRENCY_CATALOG`` above — no user input, so this f-string SQL is
        # not an injection vector.
        "INSERT INTO erp_currencies (code, name, symbol, numeric) VALUES "
        f"{currency_rows} ON CONFLICT (code) DO NOTHING"  # nosec B608
    )

    permission_rows = ", ".join(
        f"('{key}', '{description}')" for key, description in PERMISSION_CATALOG
    )
    op.execute(
        # ``permission_rows`` is built solely from the compile-time literal
        # ``PERMISSION_CATALOG`` above — no user input, so this f-string SQL is
        # not an injection vector.
        "INSERT INTO core_permissions (key, description) VALUES "
        f"{permission_rows} ON CONFLICT (key) DO NOTHING"  # nosec B608
    )


def downgrade() -> None:
    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON public.{table}")

    op.drop_index("ix_core_user_roles_role_id", table_name="core_user_roles")
    op.drop_index("ix_core_user_roles_user_id", table_name="core_user_roles")
    op.drop_table("core_user_roles")

    op.drop_table("core_roles")

    op.drop_index("ix_core_permissions_key", table_name="core_permissions")
    op.drop_table("core_permissions")

    op.drop_table("erp_currencies")

    # NOTE: current_tenant_id() is intentionally NOT dropped — identity also
    # uses it. Identity's downgrade drops the function; core's downgrade must
    # leave it in place for identity's tenant-scoped tables.
