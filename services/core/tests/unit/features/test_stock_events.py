"""Stock level change producer tests - the Rule 4 reorder-alert event.

Verifies the envelope shape (event_type + §9.3 metadata) and that
``emit_stock_level_changed`` publishes through the process-wide producer
(patched here with a recording fake).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from core.events.constants import INVENTORY_STOCK_LEVEL_CHANGED
from core.features.inventory.events.producers import (
    StockLevelChangedEvent,
    emit_stock_level_changed,
)
from core.features.inventory.events.producers import stock_events as producer_module


class RecordingProducer:
    """Drops-in for StubEventProducer.publish and records calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, StockLevelChangedEvent, str | None]] = []

    def publish(self, topic: str, event: StockLevelChangedEvent, *, key: str | None = None) -> None:
        self.calls.append((topic, event, key))


@pytest.fixture()
def producer(monkeypatch: pytest.MonkeyPatch) -> RecordingProducer:
    fake = RecordingProducer()
    monkeypatch.setattr(producer_module, "get_event_producer", lambda: fake)
    return fake


class TestStockLevelChangedEvent:
    def test_default_event_type(self) -> None:
        event = StockLevelChangedEvent(tenant_id=str(uuid.uuid4()), metadata={})
        assert event.event_type == INVENTORY_STOCK_LEVEL_CHANGED
        assert event.version == 1


class TestEmitStockLevelChanged:
    async def test_publishes_envelope_with_metadata(self, producer: RecordingProducer) -> None:
        tenant = uuid.uuid4()
        product = uuid.uuid4()
        warehouse = uuid.uuid4()

        await emit_stock_level_changed(
            tenant_id=tenant,
            product_id=product,
            warehouse_id=warehouse,
            qty_on_hand=Decimal("4.00"),
            reorder_point=Decimal("5.00"),
            breach_crossed=True,
        )

        assert len(producer.calls) == 1
        topic, event, key = producer.calls[0]
        assert topic == INVENTORY_STOCK_LEVEL_CHANGED
        assert key == str(tenant)
        assert event.tenant_id == str(tenant)
        assert event.metadata["product_id"] == str(product)
        assert event.metadata["warehouse_id"] == str(warehouse)
        assert event.metadata["qty_on_hand"] == Decimal("4.00")
        assert event.metadata["reorder_point"] == Decimal("5.00")
        assert event.metadata["breach_crossed"] is True

    async def test_no_crossing_false(self, producer: RecordingProducer) -> None:
        await emit_stock_level_changed(
            tenant_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            warehouse_id=uuid.uuid4(),
            qty_on_hand=Decimal("10"),
            reorder_point=Decimal("5"),
            breach_crossed=False,
        )
        assert producer.calls[0][1].metadata["breach_crossed"] is False
