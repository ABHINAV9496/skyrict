"""Inventory event producers."""

from core.features.inventory.events.producers.product_events import (
    ProductRemovedEvent,
    ProductUpsertedEvent,
    emit_inventory_product_removed,
    emit_inventory_product_upserted,
)
from core.features.inventory.events.producers.stock_events import (
    StockLevelChangedEvent,
    emit_stock_level_changed,
)

__all__ = [
    "ProductRemovedEvent",
    "ProductUpsertedEvent",
    "StockLevelChangedEvent",
    "emit_inventory_product_removed",
    "emit_inventory_product_upserted",
    "emit_stock_level_changed",
]
