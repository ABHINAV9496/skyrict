"""Index erp_stock_movements for stock-health analytics (INV-ANL-001).

The stock-health analytics queries filter the immutable ledger by
``(tenant_id, warehouse_id, movement_type)`` and window on ``created_at``
(dead-stock / slow-mover windows and the weekly movement-trend series). Add a
covering composite index so those reads stay sub-second on the seed dataset
(ticket requirement), independent of the existing write-oriented
``ix_erp_stock_movements_product_warehouse`` index.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-01
"""

from __future__ import annotations

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_erp_stock_movements_tenant_wh_type_created"


def upgrade() -> None:
    op.create_index(
        _INDEX_NAME,
        "erp_stock_movements",
        ["tenant_id", "warehouse_id", "movement_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="erp_stock_movements")
