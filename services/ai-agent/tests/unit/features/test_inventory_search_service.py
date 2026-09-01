"""Unit tests for the hybrid inventory search service (SKY-70).

Feature-layer orchestration with fake adapters (no models/db imports —
import-linter contract): exact-above-semantic merge + dedupe by product,
degradation to exact-only when no embedding provider or on provider failure,
cache-hit short-circuit, warehouse scoping, valuation enrichment, query-log
telemetry, and per-request limit truncation.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

import ai_agent.features.inventory_semantic.search as search_service
from ai_agent.core.embedding import EmbeddingResult
from ai_agent.db.inventory_embedding_repository import (
    InventoryEmbeddingHit,
    InventoryExactHit,
)
from ai_agent.features.inventory_semantic.search import (
    InventorySearchItem,
    InventorySearchService,
)
from ai_agent.features.nl_query.gateway import ProductRef, StockLevelRow

TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
WAREHOUSE_ID = uuid.uuid4()
P_A = uuid.uuid4()
P_B = uuid.uuid4()
P_C = uuid.uuid4()


@pytest.fixture(autouse=True)
def _noop_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _allow(**kwargs: object) -> None:
        return None

    monkeypatch.setattr(search_service.limiter, "enforce", _allow)


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
    def __init__(
        self,
        exact: list[InventoryExactHit] | None = None,
        semantic: list[InventoryEmbeddingHit] | None = None,
    ) -> None:
        self.exact = exact or []
        self.semantic = semantic or []
        self.exact_calls = 0
        self.semantic_calls = 0

    async def exact_search(
        self,
        *,
        tenant_id: uuid.UUID,
        terms: list[str],
        limit: int,
    ) -> list[InventoryExactHit]:
        self.exact_calls += 1
        return self.exact[:limit]

    async def semantic_search(
        self,
        *,
        tenant_id: uuid.UUID,
        query_vector: list[float],
        top_k: int,
    ) -> list[InventoryEmbeddingHit]:
        self.semantic_calls += 1
        return self.semantic[:top_k]


class _FakeGateway:
    def __init__(
        self,
        stock: list[StockLevelRow] | None = None,
        products: list[ProductRef] | None = None,
    ) -> None:
        self.stock = stock or []
        self.products = products or []

    async def get_stock_levels(
        self,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
    ) -> list[StockLevelRow]:
        return [
            row for row in self.stock if warehouse_id is None or row.warehouse_id == warehouse_id
        ]

    async def list_products(self) -> list[ProductRef]:
        return self.products

    async def list_warehouses(self) -> list:  # pragma: no cover - protocol tail
        return []

    async def list_movements(self, **kwargs: object) -> list:  # pragma: no cover - protocol tail
        return []


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict[tuple[uuid.UUID, str], list[dict[str, object]]] = {}

    async def get(self, *, tenant_id: uuid.UUID, query_hash: str) -> list[dict[str, object]] | None:
        return self.store.get((tenant_id, query_hash))

    async def put(
        self,
        *,
        tenant_id: uuid.UUID,
        query_hash: str,
        payload: list[dict[str, object]],
        ttl_seconds: int,
    ) -> None:
        self.store[(tenant_id, query_hash)] = payload


class _FakeQueryLog:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    async def add(self, **kwargs: object) -> object:
        self.rows.append(kwargs)
        return None


def _build(
    *,
    provider=None,
    store: _FakeStore,
    cache: _FakeCache | None = None,
    gateway: _FakeGateway | None = None,
    logs: _FakeQueryLog | None = None,
    limit: int = 20,
) -> InventorySearchService:
    return InventorySearchService(
        embedding_provider=provider,
        store=store,  # type: ignore[arg-type]
        cache=cache or _FakeCache(),  # type: ignore[arg-type]
        gateway=gateway,  # type: ignore[arg-type]
        query_logs=logs or _FakeQueryLog(),  # type: ignore[arg-type]
        limit=limit,
        semantic_top_k=50,
        cache_ttl_seconds=300,
        rate_limit_per_minute=30,
        tenant_limit_per_minute=100,
    )


def _exact(product_id: uuid.UUID, name: str, sku: str = "SKU") -> InventoryExactHit:
    return InventoryExactHit(
        product_id=product_id,
        sku=sku,
        name=name,
        category="Peripherals",
        unit="unit",
    )


def _semantic(product_id: uuid.UUID, name: str, distance: float) -> InventoryEmbeddingHit:
    return InventoryEmbeddingHit(
        product_id=product_id,
        sku="S",
        name=name,
        category="Peripherals",
        unit="unit",
        cosine_distance=distance,
        embedding_model="text-embedding-3-small",
    )


def _stock(product_id: uuid.UUID) -> StockLevelRow:
    return StockLevelRow(
        product_id=product_id,
        warehouse_id=WAREHOUSE_ID,
        qty_on_hand=10,
        qty_reserved=0,
    )


class TestExactOnlyDegradation:
    async def test_no_embedding_provider_degrades_and_skips_semantic(self) -> None:
        store = _FakeStore(exact=[_exact(P_A, "Steel Cargo Rack")])
        service = _build(provider=None, store=store)

        result = await service.search(query="cargo rack", tenant_id=TENANT_ID, user_id=USER_ID)

        assert result.degraded is True
        assert result.model_used is None
        assert store.semantic_calls == 0
        assert [item.item_id for item in result.data] == [P_A]
        assert result.data[0].source == "exact"
        assert result.data[0].score == 1.0

    async def test_provider_failure_degrades_but_keeps_exact_hits(self) -> None:
        provider = _FakeEmbeddingProvider()
        provider.failure = RuntimeError("provider down")
        store = _FakeStore(exact=[_exact(P_A, "Cargo Rack")])
        service = _build(provider=provider, store=store)

        result = await service.search(query="cargo", tenant_id=TENANT_ID, user_id=USER_ID)

        assert result.degraded is True
        assert [item.item_id for item in result.data] == [P_A]

    async def test_empty_query_returns_without_touching_adapters(self) -> None:
        store = _FakeStore()
        logs = _FakeQueryLog()
        service = _build(provider=None, store=store, logs=logs)

        result = await service.search(query="   ", tenant_id=TENANT_ID, user_id=USER_ID)

        assert result.data == []
        assert store.exact_calls == 0
        assert logs.rows == []


class TestHybridMerge:
    async def test_exact_hits_rank_above_semantic_with_dedupe(self) -> None:
        store = _FakeStore(
            exact=[_exact(P_A, "Laptop Charger 65W", sku="LAP-65W")],
            semantic=[
                _semantic(P_B, "Power Adapter", distance=0.1),
                _semantic(P_A, "Laptop Charger", distance=0.2),
            ],
        )
        service = _build(provider=_FakeEmbeddingProvider(), store=store)

        result = await service.search(query="charger", tenant_id=TENANT_ID, user_id=USER_ID)

        assert [item.item_id for item in result.data] == [P_A, P_B]
        assert result.data[0].source == "exact"
        assert result.data[1].source == "semantic"
        assert result.data[1].score == pytest.approx(0.9)
        assert result.data[1].matched_fields is None
        assert result.degraded is False
        assert result.model_used == "text-embedding-3-small"

    async def test_exact_matched_fields_are_case_insensitive(self) -> None:
        store = _FakeStore(
            exact=[_exact(P_A, "USB-C Cable", sku="CBL-CABLE"), _exact(P_B, "HDMI Cable")],
        )
        service = _build(provider=None, store=store)

        result = await service.search(query="CABLE", tenant_id=TENANT_ID, user_id=USER_ID)

        by_id = {item.item_id: item for item in result.data}
        assert "name" in (by_id[P_A].matched_fields or [])
        assert "sku" in (by_id[P_A].matched_fields or [])

    async def test_limit_truncates_merged_output(self) -> None:
        store = _FakeStore(
            exact=[_exact(P_A, "A"), _exact(P_B, "B")],
            semantic=[_semantic(uuid.uuid4(), "C", 0.05)],
        )
        service = _build(provider=_FakeEmbeddingProvider(), store=store, limit=20)

        result = await service.search(query="x", tenant_id=TENANT_ID, user_id=USER_ID, limit=1)

        assert len(result.data) == 1
        assert result.data[0].item_id == P_A


class TestCache:
    async def test_cache_hit_short_circuits_store_and_logs(self) -> None:
        store = _FakeStore(exact=[_exact(P_A, "Laptop Charger")])
        payload = [
            InventorySearchItem.from_cache_payload(
                {
                    "item_id": str(P_A),
                    "sku": "LAP",
                    "name": "Laptop Charger",
                    "category": "Peripherals",
                    "unit": "unit",
                    "source": "exact",
                    "score": 1.0,
                    "matched_fields": ["name"],
                }
            ).to_cache_payload()
        ]
        cache = _FakeCache()
        cache.store[(TENANT_ID, search_service.hash_query("charger"))] = payload
        logs = _FakeQueryLog()
        service = _build(provider=_FakeEmbeddingProvider(), store=store, cache=cache, logs=logs)

        result = await service.search(query="charger", tenant_id=TENANT_ID, user_id=USER_ID)

        assert result.cached is True
        assert store.exact_calls == 0
        assert store.semantic_calls == 0
        assert [item.item_id for item in result.data] == [P_A]
        assert logs.rows == []

    async def test_miss_writes_through_cache_with_inventory_intent(self) -> None:
        store = _FakeStore(exact=[_exact(P_A, "Laptop Charger")])
        cache = _FakeCache()
        logs = _FakeQueryLog()
        service = _build(provider=None, store=store, cache=cache, logs=logs)

        await service.search(query="Laptop Charger", tenant_id=TENANT_ID, user_id=USER_ID)

        assert cache.store

        second = await service.search(
            query=" laptop   charger ", tenant_id=TENANT_ID, user_id=USER_ID
        )
        assert second.cached is True

        assert len(logs.rows) == 1
        row = logs.rows[0]
        assert row["parsed_intent"] == {"action": "inventory_search"}
        assert row["tenant_id"] == TENANT_ID
        assert isinstance(row["latency_ms"], int)


class TestSideChannels:
    async def test_warehouse_filter_keeps_only_products_with_stock(self) -> None:
        store = _FakeStore(
            exact=[_exact(P_A, "A"), _exact(P_B, "B"), _exact(P_C, "C")],
        )
        gateway = _FakeGateway(stock=[_stock(P_A), _stock(P_C)])
        service = _build(provider=None, store=store, gateway=gateway)

        result = await service.search(
            query="x", tenant_id=TENANT_ID, user_id=USER_ID, warehouse_id=WAREHOUSE_ID
        )

        assert {item.item_id for item in result.data} == {P_A, P_C}

    async def test_valuation_enrichment_attaches_cost_prices(self) -> None:
        store = _FakeStore(exact=[_exact(P_A, "Laptop Charger")])
        gateway = _FakeGateway(
            products=[
                ProductRef(
                    id=P_A,
                    sku="LAP",
                    name="Laptop Charger",
                    reorder_point=5,
                    cost_price=Decimal("42.50"),
                )
            ]
        )
        service = _build(provider=None, store=store, gateway=gateway)

        result = await service.search(
            query="charger", tenant_id=TENANT_ID, user_id=USER_ID, valuation_enabled=True
        )

        assert result.data[0].cost_price == "42.50"

    async def test_no_valuation_header_means_no_cost_prices(self) -> None:
        store = _FakeStore(exact=[_exact(P_A, "Laptop Charger")])
        service = _build(provider=None, store=store, gateway=_FakeGateway())

        result = await service.search(
            query="charger", tenant_id=TENANT_ID, user_id=USER_ID, valuation_enabled=False
        )

        assert result.data[0].cost_price is None
