"""Product snapshot event producer tests (SKY-70).

Verifies the envelope shape (event_type + catalog metadata) for upsert/remove
and that ``emit_inventory_product_*`` publish through the process-wide
producer (patched here with a recording fake). Also covers the best-effort
HTTP sync dispatch: it is skipped when the sync token is not configured and
fires a background POST (patched out) carrying the right payload when it is.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from core.core.tenant_context import TenantContext
from core.events.constants import (
    INVENTORY_PRODUCT_REMOVED,
    INVENTORY_PRODUCT_UPSERTED,
)
from core.features.inventory.events.producers import (
    ProductRemovedEvent,
    ProductUpsertedEvent,
    emit_inventory_product_removed,
    emit_inventory_product_upserted,
)
from core.features.inventory.events.producers import product_events as producer_module


class RecordingProducer:
    """Drops-in for StubEventProducer.publish and records calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object, str | None]] = []

    def publish(self, topic: str, event: object, *, key: str | None = None) -> None:
        self.calls.append((topic, event, key))


class RecordingSyncDispatch:
    """Drops-in for product_events._post_sync and records payloads."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def post(
        self,
        *,
        payload: dict[str, object],
        sync_path: str,
        token: str,
        tenant_slug: str,
    ) -> None:
        self.calls.append(
            {
                "payload": payload,
                "sync_path": sync_path,
                "token": token,
                "tenant_slug": tenant_slug,
            }
        )


@pytest.fixture()
def producer(monkeypatch: pytest.MonkeyPatch) -> RecordingProducer:
    fake = RecordingProducer()
    monkeypatch.setattr(producer_module, "get_event_producer", lambda: fake)
    return fake


@pytest.fixture()
def dispatch(monkeypatch: pytest.MonkeyPatch) -> RecordingSyncDispatch:
    fake = RecordingSyncDispatch()
    monkeypatch.setattr(producer_module, "_post_sync", fake.post)
    return fake


def _clear_tenant() -> None:
    TenantContext.reset()
    TenantContext.set_tenant_slug(None)


class TestProductEventEnvelopes:
    def test_upserted_default_event_type(self) -> None:
        event = ProductUpsertedEvent(tenant_id=str(uuid.uuid4()), metadata={})
        assert event.event_type == INVENTORY_PRODUCT_UPSERTED
        assert event.version == 1

    def test_removed_default_event_type(self) -> None:
        event = ProductRemovedEvent(tenant_id=str(uuid.uuid4()), metadata={})
        assert event.event_type == INVENTORY_PRODUCT_REMOVED
        assert event.version == 1


class TestEmitInventoryProductUpserted:
    async def test_publishes_envelope_with_metadata(self, producer: RecordingProducer) -> None:
        tenant, product = uuid.uuid4(), uuid.uuid4()
        await emit_inventory_product_upserted(
            tenant_id=tenant,
            product_id=product,
            sku="CBL-CABLE",
            name="Cat6 Patch Cable",
            category="Networking",
            unit="m",
        )
        assert len(producer.calls) == 1
        topic, event, key = producer.calls[0]
        assert topic == INVENTORY_PRODUCT_UPSERTED
        assert key == str(tenant)
        assert event.tenant_id == str(tenant)  # type: ignore[attr-defined]
        assert event.metadata["product_id"] == str(product)  # type: ignore[attr-defined]
        assert event.metadata["sku"] == "CBL-CABLE"  # type: ignore[attr-defined]
        assert event.metadata["name"] == "Cat6 Patch Cable"  # type: ignore[attr-defined]
        assert event.metadata["category"] == "Networking"  # type: ignore[attr-defined]
        assert event.metadata["unit"] == "m"  # type: ignore[attr-defined]

    async def test_sync_disabled_token_skips_dispatch(
        self,
        producer: RecordingProducer,
        dispatch: RecordingSyncDispatch,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(producer_module.settings, "AI_SYNC_TOKEN", "")
        _clear_tenant()
        await emit_inventory_product_upserted(
            tenant_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            sku="S",
            name="N",
            category=None,
            unit=None,
        )
        await asyncio.sleep(0.01)
        assert dispatch.calls == []
        assert len(producer.calls) == 1

    async def test_sync_dispatched_as_background_post(
        self,
        producer: RecordingProducer,
        dispatch: RecordingSyncDispatch,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(producer_module.settings, "AI_SYNC_TOKEN", "secret")
        tenant, product = uuid.uuid4(), uuid.uuid4()
        _clear_tenant()
        TenantContext.set_tenant_slug("acme")
        try:
            await emit_inventory_product_upserted(
                tenant_id=tenant,
                product_id=product,
                sku="CBL-CABLE",
                name="Cat6 Patch Cable",
                category="Networking",
                unit="m",
            )
            for _ in range(50):
                if dispatch.calls:
                    break
                await asyncio.sleep(0.005)
            assert len(dispatch.calls) == 1
            call = dispatch.calls[0]
            assert call["token"] == "secret"
            assert call["tenant_slug"] == "acme"
            assert call["sync_path"] == "/api/v1/ai/inventory/embeddings/sync"
            assert call["payload"] == {
                "upserts": [
                    {
                        "product_id": str(product),
                        "sku": "CBL-CABLE",
                        "name": "Cat6 Patch Cable",
                        "category": "Networking",
                        "unit": "m",
                    }
                ],
                "removes": [],
            }
        finally:
            _clear_tenant()

    async def test_missing_slug_skips_dispatch(
        self,
        producer: RecordingProducer,
        dispatch: RecordingSyncDispatch,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(producer_module.settings, "AI_SYNC_TOKEN", "secret")
        _clear_tenant()
        await emit_inventory_product_upserted(
            tenant_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            sku="S",
            name="N",
            category=None,
            unit=None,
        )
        await asyncio.sleep(0.01)
        assert dispatch.calls == []


class TestEmitInventoryProductRemoved:
    async def test_publishes_envelope_with_metadata(self, producer: RecordingProducer) -> None:
        tenant, product = uuid.uuid4(), uuid.uuid4()
        await emit_inventory_product_removed(tenant_id=tenant, product_id=product)
        assert len(producer.calls) == 1
        topic, event, key = producer.calls[0]
        assert topic == INVENTORY_PRODUCT_REMOVED
        assert key == str(tenant)
        assert event.tenant_id == str(tenant)  # type: ignore[attr-defined]
        assert event.metadata == {"product_id": str(product)}  # type: ignore[attr-defined]

    async def test_sync_dispatched_as_background_post(
        self,
        producer: RecordingProducer,
        dispatch: RecordingSyncDispatch,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(producer_module.settings, "AI_SYNC_TOKEN", "secret")
        tenant, product = uuid.uuid4(), uuid.uuid4()
        _clear_tenant()
        TenantContext.set_tenant_slug("acme")
        try:
            await emit_inventory_product_removed(tenant_id=tenant, product_id=product)
            for _ in range(50):
                if dispatch.calls:
                    break
                await asyncio.sleep(0.005)
            assert len(dispatch.calls) == 1
            assert dispatch.calls[0]["payload"] == {
                "upserts": [],
                "removes": [{"product_id": str(product)}],
            }
        finally:
            _clear_tenant()
