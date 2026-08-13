"""Inventory feature package — products, warehouses, stock levels, movements.

Feature-based layout: every ERP module (finance, hr, sales, ...) owns its
``models/``, ``ports.py`` and ``repository.py`` inside its own package under
``core.features``, so modules never accumulate in a single models registry.
"""

from core.features.inventory.models import (
    ErpProductModel,
    ErpStockLevelModel,
    ErpStockMovementModel,
    ErpWarehouseModel,
)
from core.features.inventory.ports import InventoryRepositoryPort
from core.features.inventory.repository import InventoryRepository

__all__ = [
    "ErpProductModel",
    "ErpStockLevelModel",
    "ErpStockMovementModel",
    "ErpWarehouseModel",
    "InventoryRepository",
    "InventoryRepositoryPort",
]
