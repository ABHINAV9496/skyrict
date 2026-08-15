"""crm_sales: erp_crm_leads, erp_crm_opportunities, erp_crm_customers,
erp_sales_orders, erp_sales_order_lines

CRM-DATA-001 (SKY-43). Follows the composite-FK RLS convention established by
0001 and the enum/table pattern from 0002:

- composite PRIMARY KEY ``(tenant_id, id)`` on every table; ``tenant_id ->
  tenants(id)`` ON DELETE CASCADE;
- the composite-FK convention: every child references its parent with a
  composite FK ``(tenant_id, ref) -> parent(tenant_id, id)`` so a cross-tenant
  reference is impossible at the constraint level (referential integrity
  agrees with RLS);
- **hard product FK**: ``erp_sales_order_lines.product_id`` is a REAL composite
  FK to inventory's ``erp_products`` (RESTRICT) — a line can only reference a
  product in the same tenant, and products are never hard-deleted. This was a
  locked decision for SKY-43 (the module doc's earlier "no hard FK" note is
  superseded by the approved ticket);
- lead status (4 values: no ``converted``) and opportunity stage (6 values,
  starting at ``prospecting``) follow the locked SKY-43 enums. The opportunity
  CHECK ties each terminal stage to its timestamp and forbids both;
- ``erp_sales_orders`` carries ``UNIQUE (tenant_id, order_number)`` and the
  ``confirmed_at`` CHECK; ``erp_sales_order_lines`` carries denormalized
  ``product_name`` / ``sku`` snapshots so order history stays stable even if
  the catalog changes;
- ``erp_crm_leads`` gets a NON-unique ``(tenant_id, email)`` index — email
  dedupe is a soft service-layer probe, never a uniqueness constraint;
- money is ``Numeric(18,4)`` with ``String(3)`` currency codes FK'd to the
  global ``erp_currencies`` catalog seeded by 0001 — no float columns;
- ``owner_id`` / ``team_id`` are plain UUIDs with NO FK: they reference
  identity users (and a teams table that does not exist yet) in the shared
  database but are owned by another service's schema/RLS; validated via ports
  at the service layer (same convention as HR's ``user_id`` columns);
- seeds the three new permission keys (``erp.crm.read``, ``erp.crm.write``,
  ``erp.sales.approve``) into ``core_permissions``; ``erp.sales.read`` /
  ``erp.sales.write`` were already seeded by 0001.

NUMBERING NOTE: the ticket calls this "0003" (original plan 0001 -> 0002 ->
0003_crm_sales). 0003 never landed and 0005/0004/0006 merged instead, so the
chain is currently 0001 -> 0002 -> 0005 -> 0004 -> 0006. Following the 0004
precedent ("To honour the ticket's number while keeping a single linear
chain"), this migration is revision "0003" with down_revision "0006" — the
chain becomes 0001 -> 0002 -> 0005 -> 0004 -> 0006 -> 0003 (chain order, not
numeric order). Do not rewire 0005; its comment predates 0004/0006 landing.

DEPENDS ON identity's migration 0001 (``tenants`` + ``current_tenant_id()``),
core's 0001 (``erp_currencies`` + ``erp.sales.read/write`` seeds), and core's
0002 (``erp_products``).

Revision ID: 0003
Revises: 0006
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0006"
branch_labels = None
depends_on = None

_TENANT_SCOPED_TABLES = (
    "erp_crm_leads",
    "erp_crm_opportunities",
    "erp_crm_customers",
    "erp_sales_orders",
    "erp_sales_order_lines",
)

# New permission keys seeded by this migration (must match
# core/core/permissions.py CATALOG). erp.sales.read/write are already seeded
# by 0001 and are NOT re-seeded here.
CRM_SALES_PERMISSION_CATALOG: tuple[tuple[str, str], ...] = (
    ("erp.crm.read", "View leads, opportunities, and customers"),
    ("erp.crm.write", "Create and update leads, opportunities, and customers"),
    ("erp.sales.approve", "Confirm, fulfil, and cancel sales orders"),
)


def upgrade() -> None:
    lead_status = postgresql.ENUM(
        "new",
        "contacted",
        "qualified",
        "disqualified",
        name="erp_crm_lead_status",
    )
    opportunity_stage = postgresql.ENUM(
        "prospecting",
        "qualified",
        "proposal",
        "negotiation",
        "won",
        "lost",
        name="erp_crm_opportunity_stage",
    )
    order_status = postgresql.ENUM(
        "draft",
        "confirmed",
        "fulfilled",
        "cancelled",
        name="erp_sales_order_status",
    )
    credit_check_result = postgresql.ENUM(
        "pending",
        "passed",
        "failed",
        name="erp_sales_credit_check_result",
    )

    # --- erp_crm_leads (tenant-scoped, composite PK, RLS) ---
    op.create_table(
        "erp_crm_leads",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("status", lead_status, nullable=False, server_default=sa.text("'new'")),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("company", sa.String(255), nullable=True),
        # owner_id / team_id: plain UUIDs, NO FK (identity users / teams model
        # that does not exist yet — same convention as HR's user_id columns).
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("team_id", sa.Uuid(), nullable=True),
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
        # A lead must be identifiable by at least one contact channel.
        sa.CheckConstraint(
            "(first_name IS NOT NULL AND first_name <> '')"
            " OR (last_name IS NOT NULL AND last_name <> '')"
            " OR (email IS NOT NULL AND email <> '')",
            name="ck_erp_crm_leads_contact_present",
        ),
    )
    # NON-unique dedupe probe index — email dedupe is a soft service-layer
    # operation, never a uniqueness constraint (locked SKY-43 decision).
    op.create_index(
        "ix_erp_crm_leads_tenant_email",
        "erp_crm_leads",
        ["tenant_id", "email"],
    )
    op.create_index(
        "ix_erp_crm_leads_tenant_owner",
        "erp_crm_leads",
        ["tenant_id", "owner_id"],
    )

    # --- erp_crm_opportunities (tenant-scoped, composite PK, RLS) ---
    op.create_table(
        "erp_crm_opportunities",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "stage",
            opportunity_stage,
            nullable=False,
            server_default=sa.text("'prospecting'"),
        ),
        sa.Column("amount", sa.Numeric(18, 4), nullable=True),
        sa.Column(
            "currency_code",
            sa.String(3),
            sa.ForeignKey("erp_currencies.code"),
            nullable=True,
        ),
        sa.Column("probability", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column("won_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lost_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lost_reason", sa.String(255), nullable=True),
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
        sa.CheckConstraint(
            "amount IS NULL OR amount >= 0",
            name="ck_erp_crm_opportunities_amount_non_negative",
        ),
        sa.CheckConstraint(
            "amount IS NULL OR currency_code IS NOT NULL",
            name="ck_erp_crm_opportunities_currency_present",
        ),
        sa.CheckConstraint(
            "probability >= 0 AND probability <= 100",
            name="ck_erp_crm_opportunities_probability_range",
        ),
        # Terminal-stage bookkeeping: won_at exists iff stage = 'won',
        # lost_at exists iff stage = 'lost', and never both.
        sa.CheckConstraint(
            "((stage = 'won') = (won_at IS NOT NULL))"
            " AND ((stage = 'lost') = (lost_at IS NOT NULL))"
            " AND (NOT (won_at IS NOT NULL AND lost_at IS NOT NULL))",
            name="ck_erp_crm_opportunities_stage_outcome",
        ),
    )
    op.create_index(
        "ix_erp_crm_opportunities_tenant_stage",
        "erp_crm_opportunities",
        ["tenant_id", "stage"],
    )
    op.create_index(
        "ix_erp_crm_opportunities_tenant_owner",
        "erp_crm_opportunities",
        ["tenant_id", "owner_id"],
    )
    op.create_index(
        "ix_erp_crm_opportunities_tenant_team",
        "erp_crm_opportunities",
        ["tenant_id", "team_id"],
    )
    op.create_index(
        "ix_erp_crm_opportunities_tenant_close",
        "erp_crm_opportunities",
        ["tenant_id", "expected_close_date"],
    )

    # --- erp_crm_customers (tenant-scoped, composite PK, RLS) ---
    op.create_table(
        "erp_crm_customers",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("customer_code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        # NULL credit_limit = no limit (credit check passes); currency is only
        # meaningful alongside a limit (checked below).
        sa.Column("credit_limit", sa.Numeric(18, 4), nullable=True),
        sa.Column(
            "currency_code",
            sa.String(3),
            sa.ForeignKey("erp_currencies.code"),
            nullable=True,
        ),
        # Soft delete convention (matches erp_products / erp_warehouses) —
        # there is NO customer status enum (locked SKY-43 decision).
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
        sa.UniqueConstraint("tenant_id", "customer_code", name="uq_erp_crm_customers_tenant_code"),
        sa.CheckConstraint(
            "credit_limit IS NULL OR credit_limit >= 0",
            name="ck_erp_crm_customers_credit_limit_non_negative",
        ),
        sa.CheckConstraint(
            "credit_limit IS NULL OR currency_code IS NOT NULL",
            name="ck_erp_crm_customers_currency_present",
        ),
    )
    op.create_index(
        "ix_erp_crm_customers_tenant_name",
        "erp_crm_customers",
        ["tenant_id", "name"],
    )

    # --- erp_sales_orders (tenant-scoped, composite PK, RLS) ---
    op.create_table(
        "erp_sales_orders",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("order_number", sa.String(32), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            order_status,
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "credit_check",
            credit_check_result,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        # Totals are a cached projection: the service recomputes them from the
        # lines on every write (CRM-BE-002) — never trusted from clients.
        sa.Column("subtotal", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("discount", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("tax", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("total", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "currency_code",
            sa.String(3),
            sa.ForeignKey("erp_currencies.code"),
            nullable=False,
            server_default=sa.text("'USD'"),
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
        # Composite-FK convention: an order can only reference a customer in
        # the SAME tenant. RESTRICT: customers are soft-deleted (is_active).
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["erp_crm_customers.tenant_id", "erp_crm_customers.id"],
            ondelete="RESTRICT",
            name="fk_erp_sales_orders_customer_tenant",
        ),
        sa.UniqueConstraint("tenant_id", "order_number", name="uq_erp_sales_orders_tenant_number"),
        sa.CheckConstraint(
            "subtotal >= 0 AND discount >= 0 AND tax >= 0 AND total >= 0",
            name="ck_erp_sales_orders_amounts_non_negative",
        ),
        # confirmed_at is set exactly when an order leaves draft.
        sa.CheckConstraint(
            "(status IN ('confirmed', 'fulfilled')) = (confirmed_at IS NOT NULL)",
            name="ck_erp_sales_orders_status_confirmed_at",
        ),
    )
    op.create_index(
        "ix_erp_sales_orders_tenant_status",
        "erp_sales_orders",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_erp_sales_orders_tenant_customer",
        "erp_sales_orders",
        ["tenant_id", "customer_id"],
    )

    # --- erp_sales_order_lines (tenant-scoped, composite PK, RLS) ---
    op.create_table(
        "erp_sales_order_lines",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        # Denormalized snapshots: order history stays stable even if the
        # product catalog changes later.
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("discount", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("tax", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("line_total", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
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
        # Composite-FK convention; CASCADE for order lines (a line lives and
        # dies with its order — the finance invoice-line precedent).
        sa.ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["erp_sales_orders.tenant_id", "erp_sales_orders.id"],
            ondelete="CASCADE",
            name="fk_erp_sales_order_lines_order_tenant",
        ),
        # THE hard product FK (locked SKY-43 decision): a line can only
        # reference a product in the same tenant, RESTRICT because products
        # are soft-deleted (is_active = false), never hard-deleted.
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["erp_products.tenant_id", "erp_products.id"],
            ondelete="RESTRICT",
            name="fk_erp_sales_order_lines_product_tenant",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_erp_sales_order_lines_quantity_positive"),
        sa.CheckConstraint(
            "unit_price >= 0",
            name="ck_erp_sales_order_lines_unit_price_non_negative",
        ),
        sa.CheckConstraint(
            "discount >= 0",
            name="ck_erp_sales_order_lines_discount_non_negative",
        ),
        sa.CheckConstraint("tax >= 0", name="ck_erp_sales_order_lines_tax_non_negative"),
        sa.CheckConstraint(
            "line_total >= 0",
            name="ck_erp_sales_order_lines_total_non_negative",
        ),
    )
    op.create_index(
        "ix_erp_sales_order_lines_tenant_order",
        "erp_sales_order_lines",
        ["tenant_id", "order_id"],
    )

    # --- Row-Level Security policies ---
    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON public.{table} "
            "USING (tenant_id = public.current_tenant_id()) "
            "WITH CHECK (tenant_id = public.current_tenant_id())"
        )

    # --- Seed the new permission keys ---
    permission_rows = ", ".join(
        f"('{key}', '{description}')" for key, description in CRM_SALES_PERMISSION_CATALOG
    )
    op.execute(
        # ``permission_rows`` is built solely from the compile-time literal
        # ``CRM_SALES_PERMISSION_CATALOG`` above — no user input, so this
        # f-string SQL is not an injection vector.
        "INSERT INTO core_permissions (key, description) VALUES "
        f"{permission_rows} ON CONFLICT (key) DO NOTHING"  # nosec B608
    )


def downgrade() -> None:
    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON public.{table}")

    op.execute(
        "DELETE FROM core_permissions WHERE key IN "
        "('erp.crm.read', 'erp.crm.write', 'erp.sales.approve')"
    )

    op.drop_index("ix_erp_sales_order_lines_tenant_order", table_name="erp_sales_order_lines")
    op.drop_table("erp_sales_order_lines")

    op.drop_index("ix_erp_sales_orders_tenant_customer", table_name="erp_sales_orders")
    op.drop_index("ix_erp_sales_orders_tenant_status", table_name="erp_sales_orders")
    op.drop_table("erp_sales_orders")

    op.drop_index("ix_erp_crm_customers_tenant_name", table_name="erp_crm_customers")
    op.drop_table("erp_crm_customers")

    op.drop_index("ix_erp_crm_opportunities_tenant_close", table_name="erp_crm_opportunities")
    op.drop_index("ix_erp_crm_opportunities_tenant_team", table_name="erp_crm_opportunities")
    op.drop_index("ix_erp_crm_opportunities_tenant_owner", table_name="erp_crm_opportunities")
    op.drop_index("ix_erp_crm_opportunities_tenant_stage", table_name="erp_crm_opportunities")
    op.drop_table("erp_crm_opportunities")

    op.drop_index("ix_erp_crm_leads_tenant_owner", table_name="erp_crm_leads")
    op.drop_index("ix_erp_crm_leads_tenant_email", table_name="erp_crm_leads")
    op.drop_table("erp_crm_leads")

    op.execute("DROP TYPE IF EXISTS erp_crm_lead_status")
    op.execute("DROP TYPE IF EXISTS erp_crm_opportunity_stage")
    op.execute("DROP TYPE IF EXISTS erp_sales_order_status")
    op.execute("DROP TYPE IF EXISTS erp_sales_credit_check_result")
