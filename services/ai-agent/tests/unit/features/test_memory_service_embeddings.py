"""Unit tests for MemoryService embedding plumbing (SKY-100).

Proves that with an embedding provider wired the service embeds the query
before recall and the query/facts before store, and that without one (or on
provider failure) the repo calls carry no embedding at all - preserving the
pre-embedding behavior byte for byte.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, ClassVar
from unittest.mock import AsyncMock

from ai_agent.core.embedding import EmbeddingResult
from ai_agent.features.crm.memory import MemoryService

TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
VECTOR = [0.25] * 768


class _FakeEmbeddingProvider:
    name = "fake"
    model = "fake-emb-768"
    dims = 768

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[list[str]] = []
        self._fail = fail

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        self.calls.append(list(texts))
        if self._fail:
            raise RuntimeError("embedding backend down")
        return EmbeddingResult(
            vectors=[VECTOR for _ in texts],
            model_used=self.model,
            dims=self.dims,
            latency_ms=5,
        )


class _FakeRepo:
    def __init__(
        self,
        *,
        episodic_result: list[dict[str, Any]] | None = None,
        semantic_result: list[dict[str, Any]] | None = None,
    ) -> None:
        self.episodic_store_calls: list[dict[str, Any]] = []
        self.semantic_store_calls: list[dict[str, Any]] = []
        self.recall_episodic_calls: list[dict[str, Any]] = []
        self.recall_semantic_calls: list[dict[str, Any]] = []
        self.episodic_result = episodic_result or []
        self.semantic_result = semantic_result or []

    async def store_episodic(self, **kwargs: Any) -> None:
        self.episodic_store_calls.append(kwargs)

    async def store_semantic_facts(self, **kwargs: Any) -> None:
        self.semantic_store_calls.append(kwargs)

    async def recall_episodic(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.recall_episodic_calls.append(kwargs)
        return self.episodic_result

    async def recall_semantic(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.recall_semantic_calls.append(kwargs)
        return self.semantic_result


class _FakeLlm:
    _DEFAULT_FACTS: ClassVar[list[dict[str, Any]]] = [
        {"fact": "Prefers weekly check-ins", "category": "preference"},
    ]

    def __init__(self, facts: list[dict[str, Any]] | None = None) -> None:
        self.has_providers = True
        resolved = self._DEFAULT_FACTS if facts is None else facts
        self.complete = AsyncMock(return_value=_Completion(json.dumps(resolved)))


class _Completion:
    def __init__(self, text: str) -> None:
        self.text = text


def _service(
    *,
    provider: _FakeEmbeddingProvider | None,
    repo: _FakeRepo | None = None,
    llm_facts: list[dict[str, Any]] | None = None,
) -> tuple[MemoryService, _FakeRepo, _FakeLlm]:
    fake_repo = repo or _FakeRepo()
    llm = _FakeLlm(facts=llm_facts)
    return (
        MemoryService(  # type: ignore[arg-type]
            llm_router=llm,
            repo=fake_repo,  # type: ignore[arg-type]
            embedding_provider=provider,
        ),
        fake_repo,
        llm,
    )


class TestRecallWithoutProvider:
    async def test_recall_never_embeds_and_passes_none(self) -> None:
        service, repo, _ = _service(provider=None)

        result = await service.recall_context(tenant_id=TENANT_ID, user_id=USER_ID, query="hello")

        assert result == ""
        assert repo.recall_episodic_calls[0]["query_embedding"] is None
        assert repo.recall_semantic_calls[0]["query_embedding"] is None

    async def test_store_never_embeds(self) -> None:
        service, repo, _ = _service(provider=None)

        await service.store_after_chat(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            query="hello",
            response="hi there",
        )

        assert repo.episodic_store_calls[0]["embedding"] is None
        assert repo.episodic_store_calls[0]["embedding_model"] is None
        assert repo.semantic_store_calls[0]["embeddings"] == []
        assert repo.semantic_store_calls[0]["embedding_model"] is None


class TestRecallWithProvider:
    async def test_recall_embeds_query_and_passes_vector(self) -> None:
        provider = _FakeEmbeddingProvider()
        service, repo, _ = _service(provider=provider)

        await service.recall_context(tenant_id=TENANT_ID, user_id=USER_ID, query="hello")

        assert provider.calls == [["hello"]]
        assert repo.recall_episodic_calls[0]["query_embedding"] == VECTOR
        assert repo.recall_semantic_calls[0]["query_embedding"] == VECTOR

    async def test_recall_formats_memories_without_embedding_leak(self) -> None:
        provider = _FakeEmbeddingProvider()
        repo = _FakeRepo(
            episodic_result=[
                {
                    "query": "what is on hand?",
                    "summary": "42 units",
                    "created_at": "2026-09-01T00:00:00Z",
                }
            ],
            semantic_result=[
                {
                    "fact": "Prefers weekly check-ins",
                    "category": "preference",
                    "confidence": 0.9,
                    "entity_type": None,
                }
            ],
        )
        service, _, _ = _service(provider=provider, repo=repo)

        context = await service.recall_context(
            tenant_id=TENANT_ID, user_id=USER_ID, query="inventory"
        )

        assert "Known facts about this user/entities:" in context
        assert "Recent conversation history:" in context
        assert "what is on hand?" in context

    async def test_recall_provider_failure_degrades_to_no_embedding(self) -> None:
        provider = _FakeEmbeddingProvider(fail=True)
        service, repo, _ = _service(provider=provider)

        context = await service.recall_context(tenant_id=TENANT_ID, user_id=USER_ID, query="hello")

        assert context == ""
        assert provider.calls == [["hello"]]
        assert repo.recall_episodic_calls[0]["query_embedding"] is None
        assert repo.recall_semantic_calls[0]["query_embedding"] is None


class TestStoreWithProvider:
    async def test_store_embeds_query_and_facts(self) -> None:
        provider = _FakeEmbeddingProvider()
        service, repo, _ = _service(provider=provider)

        await service.store_after_chat(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            query="hello",
            response="hi there",
        )

        # Query embed + one facts embed (single batch for both facts).
        assert provider.calls == [["hello"], ["Prefers weekly check-ins"]]
        assert repo.episodic_store_calls[0]["embedding"] == VECTOR
        assert repo.episodic_store_calls[0]["embedding_model"] == "fake-emb-768"
        assert repo.semantic_store_calls[0]["embeddings"] == [VECTOR]
        assert repo.semantic_store_calls[0]["embedding_model"] == "fake-emb-768"

    async def test_store_provider_failure_still_persists_rows_without_embedding(self) -> None:
        provider = _FakeEmbeddingProvider(fail=True)
        service, repo, _ = _service(provider=provider)

        await service.store_after_chat(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            query="hello",
            response="hi there",
        )

        # The failure is swallowed (fire-and-forget): rows still stored.
        assert provider.calls == [["hello"], ["Prefers weekly check-ins"]]
        assert repo.episodic_store_calls
        assert repo.episodic_store_calls[0]["embedding"] is None
        # Query embed failed => no query embedding_model to carry over.
        assert repo.semantic_store_calls[0]["embedding_model"] is None

    async def test_store_without_facts_never_calls_semantic_store(self) -> None:
        provider = _FakeEmbeddingProvider()
        service, repo, _ = _service(provider=provider, llm_facts=[])

        await service.store_after_chat(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            query="hello",
            response="hi there",
        )

        assert provider.calls == [["hello"]]
        assert repo.episodic_store_calls[0]["embedding"] == VECTOR
        assert repo.semantic_store_calls == []
