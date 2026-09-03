"""inventory schema: erp_products, erp_warehouses, erp_stock_levels, erp_stock_movements

- All four tables are tenant-scoped with Row-Level Security via
  ``public.current_tenant_id()``, COMPOSITE PRIMARY KEY ``(tenant_id, id)``,
  and the 0001 composite-FK convention: child tables reference parents with a
  composite FK that includes ``tenant_id``, so referential integrity agrees
  with RLS and the cross-tenant reference hole is closed at the constraint
  level, not just filtered at query time.
- ``erp_stock_movements`` is the immutable inventory ledger: no ``updated_at``,
  ``qty != 0``, and ``UNIQUE (tenant_id, ref_type, ref_id, warehouse_id)`` so
  an idempotency probe can prove a source document line was applied to a
  warehouse exactly once (a transfer pair shares one ref across two warehouses).
- ``erp_stock_levels`` is a materialized projection of the ledger, recomputed
  on write (repository layer). Its CHECK constraints are the DB-level security
  boundary for the whole inventory module: ``qty_on_hand >= 0`` (no negative
  stock) and ``qty_reserved >= 0 AND qty_reserved <= qty_on_hand`` (no
  over-reservation) - enforced by Postgres regardless of application logic.
- ``erp_products`` FKs ``cost_currency_code`` / ``sell_currency_code`` to the
  global ``erp_currencies`` catalog seeded by 0001 (not recreated here).
- Money/quantities are ``Numeric(18,4)`` everywhere - no float columns.

DEPENDS ON identity's migration 0001 (``tenants`` + ``current_tenant_id()``)
and core's 0001 (``erp_currencies``), both of which are applied first by
``make setup``.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_TENANT_SCOPED_TABLES = (
    "erp_products",
    "erp_warehouses",
    "erp_stock_levels",
    "erp_stock_movements",
)


def upgrade() -> None:
    stock_movement_type = postgresql.ENUM(
        "receipt",
        "issue",
        "transfer",
        "adjustment",
        "reservation",
        "release",
        name="erp_stock_movement_type",
    )

    # --- erp_products (tenant-scoped, composite PK, RLS) ---
    op.create_table(
        "erp_products",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column(
            "cost_price",
            sa.Numeric(18, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cost_currency_code",
            sa.String(3),
            sa.ForeignKey("erp_currencies.code"),
            nullable=False,
            server_default=sa.text("'USD'"),
        ),
        sa.Column(
            "sell_price",
            sa.Numeric(18, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "sell_currency_code",
            sa.String(3),
            sa.ForeignKey("erp_currencies.code"),
            nullable=False,
            server_default=sa.text("'USD'"),
        ),
        sa.Column(
            "reorder_point",
            sa.Numeric(18, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
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
        sa.UniqueConstraint("tenant_id", "sku", name="uq_erp_products_tenant_sku"),
        sa.CheckConstraint("cost_price >= 0", name="ck_erp_products_cost_price_non_negative"),
        sa.CheckConstraint("sell_price >= 0", name="ck_erp_products_sell_price_non_negative"),
        sa.CheckConstraint("reorder_point >= 0", name="ck_erp_products_reorder_point_non_negative"),
    )

    # --- erp_warehouses (tenant-scoped, composite PK, RLS) ---
    op.create_table(
        "erp_warehouses",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("location", sa.String(255), nullable=True),
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
        sa.UniqueConstraint("tenant_id", "name", name="uq_erp_warehouses_tenant_name"),
    )

    # --- erp_stock_levels (materialized, composite FKs to products/warehouses) ---
    op.create_table(
        "erp_stock_levels",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column(
            "qty_on_hand",
            sa.Numeric(18, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "qty_reserved",
            sa.Numeric(18, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
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
        # Composite-FK convention: a level only ever references a product and a
        # warehouse in the SAME tenant - referential integrity agrees with RLS.
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["erp_products.tenant_id", "erp_products.id"],
            ondelete="CASCADE",
            name="fk_erp_stock_levels_product_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["erp_warehouses.tenant_id", "erp_warehouses.id"],
            ondelete="CASCADE",
            name="fk_erp_stock_levels_warehouse_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_id", "product_id", "warehouse_id", name="uq_erp_stock_levels_product_warehouse"
        ),
        sa.CheckConstraint("qty_on_hand >= 0", name="ck_erp_stock_levels_on_hand_non_negative"),
        sa.CheckConstraint(
            "qty_reserved >= 0 AND qty_reserved <= qty_on_hand",
            name="ck_erp_stock_levels_reserved_range",
        ),
    )
    op.create_index(
        "ix_erp_stock_levels_warehouse",
        "erp_stock_levels",
        ["tenant_id", "warehouse_id"],
    )

    # --- erp_stock_movements (immutable ledger, composite FKs, RESTRICT) ---
    op.create_table(
        "erp_stock_movements",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("movement_type", stock_movement_type, nullable=False),
        sa.Column("qty", sa.Numeric(18, 4), nullable=False),
        sa.Column("ref_type", sa.String(32), nullable=False),
        sa.Column("ref_id", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Composite-FK convention; RESTRICT (not CASCADE): the ledger is
        # eternal and parents are soft-deleted (is_active = false) instead.
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["erp_products.tenant_id", "erp_products.id"],
            ondelete="RESTRICT",
            name="fk_erp_stock_movements_product_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["erp_warehouses.tenant_id", "erp_warehouses.id"],
            ondelete="RESTRICT",
            name="fk_erp_stock_movements_warehouse_tenant",
        ),
        sa.CheckConstraint("qty != 0", name="ck_erp_stock_movements_qty_nonzero"),
        # Idempotency: a source document line is applied to a warehouse once.
        sa.UniqueConstraint(
            "tenant_id",
            "ref_type",
            "ref_id",
            "warehouse_id",
            name="uq_erp_stock_movements_ref",
        ),
    )
    op.create_index(
        "ix_erp_stock_movements_product_warehouse",
        "erp_stock_movements",
        ["tenant_id", "product_id", "warehouse_id"],
    )

    # --- Row-Level Security policies ---
    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON public.{table} "
            "USING (tenant_id = public.current_tenant_id()) "
            "WITH CHECK (tenant_id = public.current_tenant_id())"
        )


def downgrade() -> None:
    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON public.{table}")

    op.drop_index("ix_erp_stock_movements_product_warehouse", table_name="erp_stock_movements")
    op.drop_table("erp_stock_movements")

    op.drop_index("ix_erp_stock_levels_warehouse", table_name="erp_stock_levels")
    op.drop_table("erp_stock_levels")

    op.drop_table("erp_warehouses")

    op.drop_table("erp_products")

    op.execute("DROP TYPE IF EXISTS erp_stock_movement_type")
