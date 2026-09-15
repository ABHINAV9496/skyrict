"""Widen the stock-movement idempotency key to include product_id (B1-B3).

The existing ``uq_erp_stock_movements_ref`` key is
``(tenant_id, ref_type, ref_id, warehouse_id)``, but the bulk order methods
(``reserve_order`` / ``fulfil_order_lines``) loop over product lines with the
*same* ``ref_id`` (the order UUID) and ``step`` suffix for every product in
one warehouse.  The missing ``product_id`` means:

- A two-line order in one warehouse raises ``MovementImmutableError`` on the
  second line (B1: cross-line dedupe).
- ``fulfil_order_lines`` silently skips the RELEASE/ISSUE movements for every
  line after the first, so the ledger and the level disagree (B2: silent
  stock leak).
- A concurrent duplicate-ref reservation commits a guarded UPDATE to the level
  but the ``add_movement`` dedupes, so the reserved total inflates without a
  ledger row (B3).

The fix adds ``product_id`` to the constraint, making the key per-line as the
model docstring already intended.  The downgrade reverts to the original
four-column key.

Revision ID: 0060
Revises: 0059
Create Date: 2026-09-15
"""

from __future__ import annotations

from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None

_TABLE = "erp_stock_movements"
_CONSTRAINT = "uq_erp_stock_movements_ref"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="unique")
    op.create_unique_constraint(
        _CONSTRAINT,
        _TABLE,
        ["tenant_id", "ref_type", "ref_id", "warehouse_id", "product_id"],
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="unique")
    op.create_unique_constraint(
        _CONSTRAINT,
        _TABLE,
        ["tenant_id", "ref_type", "ref_id", "warehouse_id"],
    )
