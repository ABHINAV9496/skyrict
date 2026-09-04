"""RAG semantic retrieval service (SKY-58) - feature layer, no models/db.

Pipeline per query (all orchestration lives here, adapters stay dumb):

1. Normalize + hash the query (cache key) - BEFORE any embedding call.
2. Rate-limit (Redis fixed-window, same idiom as the NL service).
3. Hot-cache read (Redis). Hit: return cached results, skip embedding.
4. Miss: embed the normalized query, cosine-search child chunks
   (``store.semantic_search``), collapse multiple child hits per parent into
   ONE parent result (best child score wins), truncate to the return budget,
   and fetch the parent texts for generation context.
5. Write-through both cache layers via ``cache.put`` (hot) - the persistent
   ``ai_query_cache`` write is composed by the router from a repository.

Query text never appears in logs or cache keys (only the hash), keeping query
PII out of Redis keys and structured logs.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import structlog

from ai_agent.core.rate_limit import limiter
from ai_agent.features.rag.retrieval.cache import (
    QueryCache,
    hash_query,
    normalize_query,
)

if TYPE_CHECKING:
    from ai_agent.core.embedding import EmbeddingProvider
    from ai_agent.db.rag_repository import ChunkHit, ParentRecord

logger = structlog.get_logger("ai_agent.rag.retrieval")


@dataclass(frozen=True, slots=True)
class RetrievalItem:
    """One parent chunk returned for generation (score = best child match)."""

    parent_id: uuid.UUID
    source_ref: str
    module: str
    chunk_text: str
    score: float
    child_hits: int
    metadata_: dict[str, object]

    def to_cache_payload(self) -> dict[str, object]:
        """JSON-safe serialization for the Redis cache."""
        return {
            "parent_id": str(self.parent_id),
            "source_ref": self.source_ref,
            "module": self.module,
            "chunk_text": self.chunk_text,
            "score": self.score,
            "child_hits": self.child_hits,
            "metadata": self.metadata_,
        }

    @classmethod
    def from_cache_payload(cls, payload: dict[str, object]) -> RetrievalItem:
        """Rehydrate a cached payload (parent_id round-trips as a string)."""
        raw_metadata = payload.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        return cls(
            parent_id=uuid.UUID(str(payload["parent_id"])),
            source_ref=str(payload["source_ref"]),
            module=str(payload["module"]),
            chunk_text=str(payload["chunk_text"]),
            score=float(str(payload["score"])),
            child_hits=int(str(payload["child_hits"])),
            metadata_=dict(metadata),
        )


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """One semantic-search execution (or cache hit)."""

    data: list[RetrievalItem]
    model_used: str | None
    latency_ms: int
    cached: bool
    query_hash: str


class RagRetrievalStore(Protocol):
    """Persistence contract (implemented by db/rag_repository.RagRepository)."""

    async def semantic_search(
        self,
        *,
        tenant_id: uuid.UUID,
        query_vector: list[float],
        top_k: int,
        module: str | None = None,
    ) -> list[ChunkHit]: ...

    async def fetch_parents(
        self, *, tenant_id: uuid.UUID, parent_ids: list[uuid.UUID]
    ) -> list[ParentRecord]: ...


class PersistentQueryCache(Protocol):
    """Durable query-cache contract (implemented by db/query_cache_repository).

    Kept as a protocol so the feature layer stays free of ``ai_agent.db``
    imports - the router composes the repository into this slot.
    """

    async def put(
        self,
        *,
        tenant_id: uuid.UUID,
        query_hash: str,
        query_text: str,
        response: dict[str, object],
        ttl_seconds: int,
    ) -> None: ...


class RagRetrievalService:
    """Orchestrates one tenant's semantic-search use case with limits + cache."""

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        store: RagRetrievalStore,
        cache: QueryCache,
        top_k_retrieve: int,
        top_k_return: int,
        cache_ttl_seconds: int,
        rate_limit_per_minute: int,
        tenant_limit_per_minute: int,
        persistent_cache: PersistentQueryCache | None = None,
    ) -> None:
        self._embeddings = embedding_provider
        self._store = store
        self._cache = cache
        self._persistent_cache = persistent_cache
        if top_k_retrieve <= 0 or top_k_return <= 0:
            raise ValueError("top_k_retrieve and top_k_return must be positive")
        if top_k_return > top_k_retrieve:
            raise ValueError("top_k_return must not exceed top_k_retrieve")
        self._top_k_retrieve = top_k_retrieve
        self._top_k_return = top_k_return
        self._cache_ttl_seconds = cache_ttl_seconds
        self._rate_limit_per_minute = rate_limit_per_minute
        self._tenant_limit_per_minute = tenant_limit_per_minute

    async def search(
        self,
        *,
        query: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        module: str | None = None,
    ) -> RetrievalResult:
        """Run one semantic search with caching and rate limiting."""
        query_hash = hash_query(query)
        await limiter.enforce(
            key=f"ai:rag_search:{tenant_id}:{user_id}",
            limit=self._rate_limit_per_minute,
            window_seconds=60,
        )
        await limiter.enforce(
            key=f"ai:tenant_total:{tenant_id}",
            limit=self._tenant_limit_per_minute,
            window_seconds=60,
        )

        cached = await self._cache.get(tenant_id=tenant_id, query_hash=query_hash)
        if cached is not None:
            items = [RetrievalItem.from_cache_payload(item) for item in cached]
            logger.info(
                "rag.retrieval_cache_hit",
                tenant_id=str(tenant_id),
                query_hash=query_hash,
                hits=len(items),
            )
            return RetrievalResult(
                data=items,
                model_used=None,
                latency_ms=0,
                cached=True,
                query_hash=query_hash,
            )

        started = time.perf_counter()
        embedded = await self._embeddings.embed([normalize_query(query)])
        vector = embedded.vectors[0]
        if len(vector) != embedded.dims:
            # The provider contract enforces dims internally; this guard keeps
            # the invariant for any future protocol implementation.
            logger.warning(
                "rag.retrieval_dim_mismatch",
                expected=embedded.dims,
                got=len(vector),
            )

        chunks = await self._store.semantic_search(
            tenant_id=tenant_id,
            query_vector=vector,
            top_k=self._top_k_retrieve,
            module=module,
        )
        items = await self._rerank_dedup(tenant_id=tenant_id, chunks=chunks)
        latency_ms = int((time.perf_counter() - started) * 1000)

        payload = [item.to_cache_payload() for item in items]
        await self._cache.put(
            tenant_id=tenant_id,
            query_hash=query_hash,
            payload=payload,
            ttl_seconds=self._cache_ttl_seconds,
        )
        if self._persistent_cache is not None:
            # Durable layer: same upsert semantics as Redis but persisted
            # (increments hit_count on repeat queries). Failures here must
            # not fail the search - cache writes are best-effort.
            try:
                await self._persistent_cache.put(
                    tenant_id=tenant_id,
                    query_hash=query_hash,
                    query_text=normalize_query(query),
                    response={"data": payload, "model_used": embedded.model_used},
                    ttl_seconds=self._cache_ttl_seconds,
                )
            except Exception as exc:  # any persistence hiccup degrades, not fails
                logger.warning("rag.persistent_cache_put_failed", error=str(exc))

        logger.info(
            "rag.retrieval_completed",
            tenant_id=str(tenant_id),
            query_hash=query_hash,
            retrieved=len(chunks),
            returned=len(items),
            latency_ms=latency_ms,
            model_used=embedded.model_used,
        )
        return RetrievalResult(
            data=items,
            model_used=embedded.model_used,
            latency_ms=latency_ms,
            cached=False,
            query_hash=query_hash,
        )

    async def _rerank_dedup(
        self, *, tenant_id: uuid.UUID, chunks: list[ChunkHit]
    ) -> list[RetrievalItem]:
        """Collapse child hits by parent and fetch parent texts for context.

        Multiple child chunks from one parent are NOT returned separately
        (that would flood the context window with near-duplicate text); the
        best child score represents the parent, and ``child_hits`` reports
        how many snippets matched so the caller can judge competition.
        """
        best_by_parent: dict[uuid.UUID, ChunkHit] = {}
        hits: dict[uuid.UUID, int] = {}
        for chunk in chunks:
            current = best_by_parent.get(chunk.parent_id)
            if current is None or chunk.cosine_distance < current.cosine_distance:
                best_by_parent[chunk.parent_id] = chunk
            hits[chunk.parent_id] = hits.get(chunk.parent_id, 0) + 1

        ordered = sorted(
            best_by_parent.values(),
            key=lambda c: c.cosine_distance,
        )[: self._top_k_return]

        parents = await self._store.fetch_parents(
            tenant_id=tenant_id,
            parent_ids=[c.parent_id for c in ordered],
        )
        parent_by_id = {p.parent_id: p for p in parents}

        items: list[RetrievalItem] = []
        for chunk in ordered:
            parent = parent_by_id.get(chunk.parent_id)
            items.append(
                RetrievalItem(
                    parent_id=chunk.parent_id,
                    source_ref=chunk.source_ref,
                    module=chunk.module,
                    chunk_text=parent.chunk_text if parent else chunk.chunk_text,
                    score=round(1.0 - chunk.cosine_distance, 4),
                    child_hits=hits[chunk.parent_id],
                    metadata_=chunk.metadata_,
                )
            )
        return items
