"""Inventory semantic + exact product search (SKY-70) - feature layer.

Hybrid pipeline: exact (ILIKE substring) hits ALWAYS rank above semantic
(cosine vector) hits, merged and deduplicated by ``product_id``. The search
degrades gracefully by design - a missing embedding provider, a provider
failure, or a Redis blip never fails the request; each produces exact-only
results surfaced as ``degraded=true`` on the response.

Layering (import-linter "feature layer, no models/db"):
- the embedding/exact store is a protocol implemented by the DB repository;
- the inventory gateway (reads core) is consulted ONLY for the optional
  warehouse filter and valuation enrichment - never for the search itself;
- Redis hot-cache and the rate limiter are foundations, reused from the RAG
  retrieval stack (distinct key prefix keeps the keyspaces separate).

Query text never appears in logs or cache keys (only the hash), and cache
payloads carry the merged pre-filter items so a warehouse/valuation side
channel can be applied per request without invalidating the cache.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, Protocol

import structlog

from ai_agent.core.rate_limit import limiter
from ai_agent.features.rag.retrieval.cache import (
    QueryCache,
    hash_query,
    normalize_query,
)

if TYPE_CHECKING:
    from decimal import Decimal

    from ai_agent.core.embedding import EmbeddingProvider
    from ai_agent.db.inventory_embedding_repository import (
        InventoryEmbeddingHit,
        InventoryExactHit,
    )
    from ai_agent.features.nl_query.gateway import InventoryGatewayPort

logger = structlog.get_logger("ai_agent.inventory_search")

_QUERY_LOG_INTENT: dict[str, object] = {"action": "inventory_search"}


@dataclass(frozen=True, slots=True)
class InventorySearchItem:
    """One product result with its provenance (exact vs semantic)."""

    item_id: uuid.UUID
    sku: str
    name: str
    category: str | None
    unit: str | None
    source: Literal["exact", "semantic"]
    score: float
    # Present only for exact hits (a concatenated embedding cannot be
    # attributed to one field); semantic hits carry score + source instead.
    matched_fields: list[str] | None
    # Local-only money data (spec §5.5): attached ONLY when the core proxy
    # forwarded X-AI-Valuation-Disclosed (tenant holds erp.inventory.valuation).
    cost_price: str | None = None

    def to_cache_payload(self) -> dict[str, object]:
        """JSON-safe serialization for the Redis cache."""
        return {
            "item_id": str(self.item_id),
            "sku": self.sku,
            "name": self.name,
            "category": self.category,
            "unit": self.unit,
            "source": self.source,
            "score": self.score,
            "matched_fields": self.matched_fields,
        }

    @classmethod
    def from_cache_payload(cls, payload: dict[str, object]) -> InventorySearchItem:
        """Rehydrate a cached payload (item_id round-trips as a string)."""
        raw_fields = payload.get("matched_fields")
        fields = None
        if isinstance(raw_fields, list) and all(isinstance(f, str) for f in raw_fields):
            fields = list(raw_fields)
        raw_category = payload.get("category")
        raw_unit = payload.get("unit")
        return cls(
            item_id=uuid.UUID(str(payload["item_id"])),
            sku=str(payload["sku"]),
            name=str(payload["name"]),
            category=raw_category if isinstance(raw_category, str) else None,
            unit=raw_unit if isinstance(raw_unit, str) else None,
            source="exact" if payload.get("source") == "exact" else "semantic",
            score=float(str(payload["score"])),
            matched_fields=fields,
        )


@dataclass(frozen=True, slots=True)
class InventorySearchResult:
    """One search execution (or cache hit) with degradation status."""

    data: list[InventorySearchItem]
    cached: bool
    degraded: bool
    model_used: str | None
    latency_ms: int


class InventoryEmbeddingStore(Protocol):
    """Persistence contract (implemented by db/inventory_embedding_repository)."""

    async def exact_search(
        self,
        *,
        tenant_id: uuid.UUID,
        terms: list[str],
        limit: int,
    ) -> list[InventoryExactHit]:
        """Substring hits over the snapshot text (never raises)."""
        ...

    async def semantic_search(
        self,
        *,
        tenant_id: uuid.UUID,
        query_vector: list[float],
        top_k: int,
    ) -> list[InventoryEmbeddingHit]:
        """Cosine-similarity hits over the snapshot embeddings."""
        ...


class QueryLogWriter(Protocol):
    """Append-only query-log contract (implemented by QueryLogRepository)."""

    async def add(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        query_text: str,
        parsed_intent: dict[str, object] | None,
        result_summary: str | None,
        model_used: str | None,
        latency_ms: int | None,
    ) -> object: ...


class InventorySearchService:
    """Orchestrates one tenant's hybrid product search with limits + cache."""

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider | None,
        store: InventoryEmbeddingStore,
        cache: QueryCache,
        gateway: InventoryGatewayPort | None,
        query_logs: QueryLogWriter,
        limit: int,
        semantic_top_k: int,
        cache_ttl_seconds: int,
        rate_limit_per_minute: int,
        tenant_limit_per_minute: int,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if semantic_top_k <= 0:
            raise ValueError("semantic_top_k must be positive")
        self._embeddings = embedding_provider
        self._store = store
        self._cache = cache
        self._gateway = gateway
        self._query_logs = query_logs
        self._limit = limit
        self._semantic_top_k = semantic_top_k
        self._cache_ttl_seconds = cache_ttl_seconds
        self._rate_limit_per_minute = rate_limit_per_minute
        self._tenant_limit_per_minute = tenant_limit_per_minute

    async def search(
        self,
        *,
        query: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        warehouse_id: uuid.UUID | None = None,
        valuation_enabled: bool = False,
        limit: int | None = None,
    ) -> InventorySearchResult:
        """Run one hybrid search; degenerates to exact-only when degraded."""
        normalized = normalize_query(query)
        terms = normalized.split()
        if not terms:
            return InventorySearchResult(
                data=[], cached=False, degraded=False, model_used=None, latency_ms=0
            )
        query_hash = hash_query(normalized)
        await limiter.enforce(
            key=f"ai:inv_search:{tenant_id}:{user_id}",
            limit=self._rate_limit_per_minute,
            window_seconds=60,
        )
        await limiter.enforce(
            key=f"ai:tenant_total:{tenant_id}",
            limit=self._tenant_limit_per_minute,
            window_seconds=60,
        )

        started = time.perf_counter()

        cached = await self._cache.get(tenant_id=tenant_id, query_hash=query_hash)
        if cached is not None:
            items = [InventorySearchItem.from_cache_payload(item) for item in cached]
            items = self._truncate(
                await self._filter_and_enrich(
                    items=items,
                    warehouse_id=warehouse_id,
                    valuation_enabled=valuation_enabled,
                ),
                limit=limit,
            )
            logger.info(
                "inventory_search.cache_hit",
                tenant_id=str(tenant_id),
                query_hash=query_hash,
                hits=len(items),
            )
            return InventorySearchResult(
                data=items,
                cached=True,
                degraded=False,
                model_used=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        degraded = self._embeddings is None
        model_used: str | None = None

        exact_items = [
            _exact_item(hit, terms)
            for hit in await self._store.exact_search(
                tenant_id=tenant_id, terms=terms, limit=self._limit
            )
        ]

        semantic_items: list[InventorySearchItem] = []
        if not degraded and self._embeddings is not None:
            try:
                embedded = await self._embeddings.embed([normalized])
                vector = embedded.vectors[0]
                model_used = embedded.model_used
                hits = await self._store.semantic_search(
                    tenant_id=tenant_id,
                    query_vector=vector,
                    top_k=self._semantic_top_k,
                )
                semantic_items = [_semantic_item(hit) for hit in hits]
            except Exception as exc:
                # Embedding/semantic failures degrade to exact-only - the
                # catalog is still searchable, just without synonyms/fuzz.
                logger.warning("inventory_search.semantic_degraded", error=str(exc))
                degraded = True

        items = _merge_exact_then_semantic(
            exact=exact_items, semantic=semantic_items, limit=self._effective_limit(limit)
        )

        payload = [item.to_cache_payload() for item in items]
        await self._cache.put(
            tenant_id=tenant_id,
            query_hash=query_hash,
            payload=payload,
            ttl_seconds=self._cache_ttl_seconds,
        )

        items = self._truncate(
            await self._filter_and_enrich(
                items=items,
                warehouse_id=warehouse_id,
                valuation_enabled=valuation_enabled,
            ),
            limit=limit,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        await self._query_logs.add(
            tenant_id=tenant_id,
            user_id=user_id,
            query_text=query,
            parsed_intent=_QUERY_LOG_INTENT,
            result_summary=str(len(items)),
            model_used=model_used,
            latency_ms=latency_ms,
        )
        logger.info(
            "inventory_search.completed",
            tenant_id=str(tenant_id),
            query_hash=query_hash,
            degraded=degraded,
            hits=len(items),
            latency_ms=latency_ms,
            model_used=model_used,
        )
        return InventorySearchResult(
            data=items,
            cached=False,
            degraded=degraded,
            model_used=model_used,
            latency_ms=latency_ms,
        )

    async def _filter_and_enrich(
        self,
        *,
        items: list[InventorySearchItem],
        warehouse_id: uuid.UUID | None,
        valuation_enabled: bool,
    ) -> list[InventorySearchItem]:
        """Per-request side-channels: warehouse scoping + valuation prices.

        Both are BEST-EFFORT: a core hiccup must not fail an already-solved
        search, so each failure logs and leaves the result unfiltered.
        """
        if warehouse_id is not None and self._gateway is not None:
            try:
                stock = await self._gateway.get_stock_levels(warehouse_id=warehouse_id)
                allowed = {row.product_id for row in stock}
                items = [item for item in items if item.item_id in allowed]
            except Exception as exc:
                logger.warning(
                    "inventory_search.warehouse_filter_degraded",
                    error=str(exc),
                    warehouse_id=str(warehouse_id),
                )

        if valuation_enabled and self._gateway is not None and items:
            try:
                costs = {
                    product.id: product.cost_price
                    for product in await self._gateway.list_products()
                }
                items = [
                    replace(item, cost_price=_format_cost(costs.get(item.item_id)))
                    for item in items
                ]
            except Exception as exc:
                logger.warning("inventory_search.valuation_degraded", error=str(exc))

        return items

    def _effective_limit(self, limit: int | None) -> int:
        return limit if limit is not None else self._limit

    def _truncate(
        self, items: list[InventorySearchItem], *, limit: int | None
    ) -> list[InventorySearchItem]:
        if limit is None:
            return items
        return items[:limit]


def _exact_item(hit: InventoryExactHit, terms: list[str]) -> InventorySearchItem:
    fields = (
        ("sku", hit.sku),
        ("name", hit.name),
        ("category", hit.category),
        ("unit", hit.unit),
    )
    matched = [
        name
        for name, value in fields
        if value is not None and any(term in value.lower() for term in terms)
    ]
    return InventorySearchItem(
        item_id=hit.product_id,
        sku=hit.sku,
        name=hit.name,
        category=hit.category,
        unit=hit.unit,
        source="exact",
        score=1.0,
        matched_fields=matched or None,
    )


def _semantic_item(hit: InventoryEmbeddingHit) -> InventorySearchItem:
    return InventorySearchItem(
        item_id=hit.product_id,
        sku=hit.sku,
        name=hit.name,
        category=hit.category,
        unit=hit.unit,
        source="semantic",
        score=round(1.0 - hit.cosine_distance, 4),
        matched_fields=None,
    )


def _merge_exact_then_semantic(
    *,
    exact: list[InventorySearchItem],
    semantic: list[InventorySearchItem],
    limit: int,
) -> list[InventorySearchItem]:
    """Exact hits always win; semantic fills the budget after dedupe."""
    exact_ordered = sorted(
        exact,
        key=lambda item: (-len(item.matched_fields or ()), item.sku),
    )
    seen: set[uuid.UUID] = set()
    merged: list[InventorySearchItem] = []
    for item in [*exact_ordered, *semantic]:
        if item.item_id in seen:
            continue
        seen.add(item.item_id)
        merged.append(item)
        if len(merged) >= limit:
            break
    return merged


def _format_cost(cost: Decimal | None) -> str | None:
    if cost is None:
        return None
    return str(cost)
