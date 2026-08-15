"""Stock level change producer — the reorder-alert fire mechanism (Rule 4 / §9).

Emits the ``inventory.stock.level_changed`` envelope through the process-wide
producer (``core.events.producers``), which in Phase 1 is the structlog stub
that logs the exact payload Kafka will carry. The service calls this AFTER the
transaction that mutated the level has committed, so a rolled-back mutation can
never emit a phantom event.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from core.events.constants import INVENTORY_STOCK_LEVEL_CHANGED
from core.events.producers import get_event_producer
from skyrict_events.base import BaseEvent


class StockLevelChangedEvent(BaseEvent):
    """Envelope for ``inventory.stock.level_changed``.

    Metadata follows §9.3: ``product_id``, ``warehouse_id``, ``qty_on_hand``,
    ``reorder_point`` and ``breach_crossed`` (true only when the level crossed
    from above to at/below the reorder point — the single-fire alert trigger).
    """

    event_type: str = INVENTORY_STOCK_LEVEL_CHANGED


async def emit_stock_level_changed(
    *,
    tenant_id: str | uuid.UUID,
    product_id: str | uuid.UUID,
    warehouse_id: str | uuid.UUID,
    qty_on_hand: Decimal,
    reorder_point: Decimal,
    breach_crossed: bool,
) -> None:
    """Publish a ``inventory.stock.level_changed`` event for one product/warehouse."""
    event = StockLevelChangedEvent(
        tenant_id=str(tenant_id),
        metadata={
            "product_id": str(product_id),
            "warehouse_id": str(warehouse_id),
            "qty_on_hand": qty_on_hand,
            "reorder_point": reorder_point,
            "breach_crossed": breach_crossed,
        },
    )
    get_event_producer().publish(
        INVENTORY_STOCK_LEVEL_CHANGED,
        event,
        key=str(tenant_id),
    )
