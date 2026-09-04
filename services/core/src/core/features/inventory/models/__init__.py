"""Inventory ORM models - registered on ``Base.metadata`` by alembic/env.py.

Feature models are NOT re-exported from ``core.models``: importing that package
from ``core.features`` would violate the import-linter layering contract, so
the migration runner imports these models directly.
"""

from core.features.inventory.models.product import ErpProductModel
from core.features.inventory.models.report_snapshot import ErpReportSnapshotModel
from core.features.inventory.models.stock_level import ErpStockLevelModel
from core.features.inventory.models.stock_movement import ErpStockMovementModel
from core.features.inventory.models.warehouse import ErpWarehouseModel

__all__ = [
    "ErpProductModel",
    "ErpReportSnapshotModel",
    "ErpStockLevelModel",
    "ErpStockMovementModel",
    "ErpWarehouseModel",
]
