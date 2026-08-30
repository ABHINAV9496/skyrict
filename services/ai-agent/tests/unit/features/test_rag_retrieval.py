"""Unit tests for the RAG retrieval service (SKY-58).

Feature-layer orchestration with fake adapters: hash/cache semantics, cache-hit
short-circuit (no embedding call), miss path (dedupe by parent, fetch parent
texts, truncation to the return budget), and the write-through to both cache
layers. No models/db imports — import-linter contract.
"""

from __future__ import annotations

import uuid

import pytest

import ai_agent.features.rag.retrieval.service as retrieval_service
from ai_agent.core.embedding import EmbeddingResult
from ai_agent.db.rag_repository import ChunkHit, ParentRecord
from ai_agent.features.rag.retrieval import (
    RagRetrievalService,
    RedisQueryCache,
    hash_query,
    normalize_query,
)
from ai_agent.features.rag.retrieval.service import RetrievalItem


@pytest.fixture(autouse=True)
def _noop_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the Redis-backed limiter so unit tests never touch the network."""

    async def _allow(**kwargs: object) -> None:
        return None

    monkeypatch.setattr(retrieval_service.limiter, "enforce", _allow)


TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
PARENT_A = uuid.uuid4()
PARENT_B = uuid.uuid4()
PARENT_C = uuid.uuid4()


class _FakeEmbeddingProvider:
    name = "openai"
    model = "text-embedding-3-small"
    dims = 4

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        self.calls.append(texts)
        return EmbeddingResult(
            vectors=[[0.1, 0.2, 0.3, 0.4] for _ in texts],
            model_used=self.model,
            dims=self.dims,
            latency_ms=7,
        )


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict[tuple[uuid.UUID, str], list[dict[str, object]]] = {}
        self.puts: list[tuple[uuid.UUID, str, int]] = []

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
        self.puts.append((tenant_id, query_hash, ttl_seconds))


class _FakePersistentCache:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def put(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


class _FakeStore:
    def __init__(self, chunks: list[ChunkHit], parents: list[ParentRecord]) -> None:
        self.chunks = chunks
        self.parents = parents
        self.search_calls = 0
        self.parent_calls = 0

    async def semantic_search(
        self,
        *,
        tenant_id: uuid.UUID,
        query_vector: list[float],
        top_k: int,
        module: str | None = None,
    ) -> list[ChunkHit]:
        self.search_calls += 1
        return self.chunks[:top_k]

    async def fetch_parents(
        self, *, tenant_id: uuid.UUID, parent_ids: list[uuid.UUID]
    ) -> list[ParentRecord]:
        self.parent_calls += 1
        by_id = {p.parent_id: p for p in self.parents}
        return [by_id[pid] for pid in parent_ids if pid in by_id]


def _chunk(parent_id: uuid.UUID, distance: float) -> ChunkHit:
    return ChunkHit(
        chunk_id=uuid.uuid4(),
        parent_id=parent_id,
        source_ref="guide.md",
        module="docs",
        chunk_text=f"child of {parent_id}",
        chunk_index=0,
        metadata_={"section": "intro"},
        cosine_distance=distance,
    )


def _parent(parent_id: uuid.UUID) -> ParentRecord:
    return ParentRecord(
        parent_id=parent_id,
        source_ref="guide.md",
        module="docs",
        chunk_text=f"parent text {parent_id}",
        metadata_={},
    )


def _service(
    *,
    provider: _FakeEmbeddingProvider | None = None,
    store: _FakeStore | None = None,
    cache: _FakeCache | None = None,
    persistent: _FakePersistentCache | None = None,
    top_k_return: int = 3,
) -> tuple[
    RagRetrievalService, _FakeEmbeddingProvider, _FakeStore, _FakeCache, _FakePersistentCache
]:
    provider = provider or _FakeEmbeddingProvider()
    store = store or _FakeStore([], [])
    cache = cache or _FakeCache()
    persistent = persistent or _FakePersistentCache()
    service = RagRetrievalService(
        embedding_provider=provider,  # type: ignore[arg-type]
        store=store,  # type: ignore[arg-type]
        cache=cache,  # type: ignore[arg-type]
        top_k_retrieve=10,
        top_k_return=top_k_return,
        cache_ttl_seconds=3600,
        rate_limit_per_minute=30,
        tenant_limit_per_minute=100,
        persistent_cache=persistent,  # type: ignore[arg-type]
    )
    return service, provider, store, cache, persistent


class TestQueryHashing:
    def test_trivial_edits_collapse_to_the_same_hash(self) -> None:
        assert hash_query("  How   do I reorder   stock? ") == hash_query("how do i reorder stock?")
        assert hash_query("Alpha") == hash_query("alpha")

    def test_normalize_collapses_whitespace_and_case(self) -> None:
        assert normalize_query("  Laptop  Charger \t 65W  ") == "laptop charger 65w"


class TestSearch:
    async def test_cache_hit_short_circuits_embedding_and_store(self) -> None:
        cache = _FakeCache()
        payload = [
            RetrievalItem(
                parent_id=PARENT_A,
                source_ref="x.md",
                module="docs",
                chunk_text="cached parent",
                score=0.95,
                child_hits=2,
                metadata_={"section": "intro"},
            ).to_cache_payload()
        ]
        query_hash = hash_query("reorder stock")
        cache.store[(TENANT_ID, query_hash)] = payload

        service, provider, store, _cache, persistent = _service(cache=cache)
        result = await service.search(query="Reorder   stock", tenant_id=TENANT_ID, user_id=USER_ID)

        assert result.cached is True
        assert provider.calls == []
        assert store.search_calls == 0
        assert persistent.calls == []
        assert result.latency_ms == 0
        assert result.query_hash == query_hash
        assert result.data[0].chunk_text == "cached parent"
        assert result.data[0].score == 0.95

    async def test_miss_retrieves_dedupes_and_fetches_parent_texts(self) -> None:
        store = _FakeStore(
            chunks=[
                _chunk(PARENT_A, 0.10),
                _chunk(PARENT_A, 0.05),  # same parent, better score
                _chunk(PARENT_B, 0.20),
            ],
            parents=[_parent(PARENT_A), _parent(PARENT_B)],
        )
        service, provider, _store, cache, persistent = _service(store=store)

        result = await service.search(query="reorder stock", tenant_id=TENANT_ID, user_id=USER_ID)

        assert result.cached is False
        assert provider.calls == [["reorder stock"]]
        # Parent A collapsed to ONE item with the best child score.
        by_parent = {item.parent_id: item for item in result.data}
        assert set(by_parent) == {PARENT_A, PARENT_B}
        assert by_parent[PARENT_A].child_hits == 2
        assert by_parent[PARENT_A].score == pytest.approx(0.95)  # 1 - 0.05
        assert by_parent[PARENT_B].score == pytest.approx(0.80)
        assert by_parent[PARENT_A].chunk_text == f"parent text {PARENT_A}"
        assert result.model_used == "text-embedding-3-small"

        # Write-through: hot cache + durable cache both populated.
        query_hash = hash_query("reorder stock")
        assert (TENANT_ID, query_hash) in cache.store
        assert len(persistent.calls) == 1
        assert persistent.calls[0]["query_text"] == "reorder stock"
        assert persistent.calls[0]["ttl_seconds"] == 3600

    async def test_truncates_to_return_budget(self) -> None:
        store = _FakeStore(
            chunks=[_chunk(PARENT_A, 0.1), _chunk(PARENT_B, 0.2), _chunk(PARENT_C, 0.3)],
            parents=[_parent(PARENT_A), _parent(PARENT_B), _parent(PARENT_C)],
        )
        service, _provider, _store, _cache, _persistent = _service(store=store, top_k_return=2)

        result = await service.search(query="x", tenant_id=TENANT_ID, user_id=USER_ID)

        assert len(result.data) == 2
        assert [item.parent_id for item in result.data] == [PARENT_A, PARENT_B]

    async def test_persistent_cache_failure_does_not_fail_search(self) -> None:
        class BrokenPersistent(_FakePersistentCache):
            async def put(self, **kwargs: object) -> None:
                raise RuntimeError("db down")

        store = _FakeStore(chunks=[_chunk(PARENT_A, 0.1)], parents=[_parent(PARENT_A)])
        service, _provider, _store, cache, _persistent = _service(
            store=store, persistent=BrokenPersistent()
        )

        result = await service.search(query="x", tenant_id=TENANT_ID, user_id=USER_ID)

        assert result.cached is False
        assert len(result.data) == 1
        assert (TENANT_ID, hash_query("x")) in cache.store  # hot layer still written


class TestRedisCacheFailOpen:
    def test_prefers_injected_client(self) -> None:
        cache = RedisQueryCache(client=None)
        assert cache._get_client() is not None  # module-level lazy client


def test_top_k_return_must_not_exceed_retrieve() -> None:
    with pytest.raises(ValueError, match="top_k_return"):
        _service(top_k_return=11)  # top_k_retrieve is 10
