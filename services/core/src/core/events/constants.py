"""Event topic constants - single source of truth for Kafka topic names.

Topics follow the ``{domain}.{entity}.{action}`` convention. Phase 1 emits
these via the structlog stub producer (``core.events.producers``); Kafka wiring
later consumes the same constants with no call-site change.
"""

from __future__ import annotations

INVENTORY_STOCK_LEVEL_CHANGED = "inventory.stock.level_changed"
INVENTORY_PRODUCT_UPSERTED = "inventory.product.upserted"
INVENTORY_PRODUCT_REMOVED = "inventory.product.removed"

__all__ = [
    "INVENTORY_PRODUCT_REMOVED",
    "INVENTORY_PRODUCT_UPSERTED",
    "INVENTORY_STOCK_LEVEL_CHANGED",
]
