"""Unit tests for the inventory snapshot sync service (SKY-70).

Feature-layer orchestration with fake adapters (no models/db — import-linter
contract): embedding-text building matches the migration 0012 string, one
batch applies removes-first then embeds/persists upserts, and a missing
embedding provider degrades to removes-only (``skipped=True``) instead of
erroring.
"""

from __future__ import annotations

import uuid

import pytest

from ai_agent.core.embedding import EmbeddingResult
from ai_agent.features.inventory_semantic.snapshot import (
    InventorySnapshotSyncService,
    ProductSnapshot,
    build_embedding_text,
)

TENANT_ID = uuid.uuid4()
P_A = uuid.uuid4()
P_B = uuid.uuid4()


class _FakeEmbeddingProvider:
    name = "openai"
    model = "text-embedding-3-small"
    dims = 4

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.failure: Exception | None = None

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        self.calls.append(texts)
        if self.failure is not None:
            raise self.failure
        return EmbeddingResult(
            vectors=[[0.1, 0.2, 0.3, 0.4] for _ in texts],
            model_used=self.model,
            dims=self.dims,
            latency_ms=7,
        )


class _FakeStore:
    def __init__(self) -> None:
        self.upserts: list[dict[str, object]] = []
        self.deletes: list[dict[str, object]] = []

    async def upsert(
        self,
        *,
        tenant_id: uuid.UUID,
        product_id: uuid.UUID,
        sku: str,
        name: str,
        category: str | None,
        unit: str | None,
        embedding: list[float],
        embedding_model: str,
        dims: int,
    ) -> None:
        self.upserts.append(
            {
                "tenant_id": tenant_id,
                "product_id": product_id,
                "sku": sku,
                "name": name,
                "category": category,
                "unit": unit,
                "embedding": embedding,
                "embedding_model": embedding_model,
                "dims": dims,
            }
        )

    async def delete(
        self,
        *,
        tenant_id: uuid.UUID,
        product_id: uuid.UUID,
    ) -> None:
        self.deletes.append({"tenant_id": tenant_id, "product_id": product_id})


def _product(pid: uuid.UUID, category: str | None = None) -> ProductSnapshot:
    return ProductSnapshot(
        product_id=pid,
        sku=f"SKU-{pid.hex[:6]}",
        name="Cat6 Patch Cable",
        category=category,
        unit="m",
    )


class TestBuildEmbeddingText:
    def test_concatenates_fields_with_single_spaces(self) -> None:
        assert (
            build_embedding_text(
                sku="CBL-100", name="Cat6 Patch Cable", category="Networking", unit="m"
            )
            == "CBL-100 Cat6 Patch Cable Networking m"
        )

    @pytest.mark.parametrize(
        ("category", "unit", "expected"),
        [
            (None, None, "CBL-100 Cat6 Patch Cable"),
            ("Networking", None, "CBL-100 Cat6 Patch Cable Networking"),
            (None, "m", "CBL-100 Cat6 Patch Cable m"),
            ("", "", "CBL-100 Cat6 Patch Cable"),
        ],
    )
    def test_drops_empty_and_none_parts(
        self, category: str | None, unit: str | None, expected: str
    ) -> None:
        assert (
            build_embedding_text(
                sku="CBL-100", name="Cat6 Patch Cable", category=category, unit=unit
            )
            == expected
        )


class TestInventorySnapshotSyncService:
    async def test_applies_removes_then_embeds_and_upserts(self) -> None:
        provider = _FakeEmbeddingProvider()
        store = _FakeStore()
        service = InventorySnapshotSyncService(embedding_provider=provider, store=store)
        removed = uuid.uuid4()

        report = await service.apply(
            tenant_id=TENANT_ID,
            upserts=[_product(P_A, category="Networking"), _product(P_B)],
            removes=[removed],
        )

        assert store.deletes == [{"tenant_id": TENANT_ID, "product_id": removed}]
        assert provider.calls == [
            [
                f"SKU-{P_A.hex[:6]} Cat6 Patch Cable Networking m",
                f"SKU-{P_B.hex[:6]} Cat6 Patch Cable m",
            ]
        ]
        assert [entry["product_id"] for entry in store.upserts] == [P_A, P_B]
        assert store.upserts[0]["category"] == "Networking"
        assert all(
            entry["embedding"] == [0.1, 0.2, 0.3, 0.4] and entry["dims"] == 4
            for entry in store.upserts
        )
        assert report.upserts_applied == 2
        assert report.removes_applied == 1
        assert report.skipped is False
        assert report.model_used == "text-embedding-3-small"
        assert report.dims == 4

    async def test_removes_apply_even_without_embedding_provider(self) -> None:
        store = _FakeStore()
        service = InventorySnapshotSyncService(embedding_provider=None, store=store)
        removed = uuid.uuid4()

        report = await service.apply(
            tenant_id=TENANT_ID,
            upserts=[_product(P_A)],
            removes=[removed],
        )

        assert store.deletes == [{"tenant_id": TENANT_ID, "product_id": removed}]
        assert store.upserts == []
        assert report.upserts_applied == 0
        assert report.removes_applied == 1
        assert report.skipped is True
        assert report.model_used is None

    async def test_embeds_nothing_when_no_upserts(self) -> None:
        provider = _FakeEmbeddingProvider()
        store = _FakeStore()
        service = InventorySnapshotSyncService(embedding_provider=provider, store=store)
        removed = uuid.uuid4()

        report = await service.apply(
            tenant_id=TENANT_ID,
            upserts=[],
            removes=[removed],
        )

        assert provider.calls == []
        assert store.deletes == [{"tenant_id": TENANT_ID, "product_id": removed}]
        assert report.upserts_applied == 0
        assert report.removes_applied == 1
        assert report.skipped is False
        assert report.dims is None

    async def test_embed_failure_propagates_before_any_upsert(self) -> None:
        provider = _FakeEmbeddingProvider()
        provider.failure = RuntimeError("provider down")
        store = _FakeStore()
        service = InventorySnapshotSyncService(embedding_provider=provider, store=store)

        with pytest.raises(RuntimeError, match="provider down"):
            await service.apply(
                tenant_id=TENANT_ID,
                upserts=[_product(P_A)],
                removes=[],
            )

        assert store.upserts == []
        assert store.deletes == []
