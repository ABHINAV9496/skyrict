"""Unit tests for the RAG ingestion orchestrator (SKY-58).

The service chunks documents, embeds every child in ONE provider batch, and
hands aligned parent/vector pairs to an injected repository - pure feature
layer, no models/db imports (import-linter contract).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from ai_agent.core.chunker import ParentChunk
from ai_agent.core.embedding import EmbeddingResult
from ai_agent.core.exceptions import AiInvalidResponseError
from ai_agent.core.token_counter import TokenCounter
from ai_agent.features.rag.ingest.loader import SourceDocument
from ai_agent.features.rag.ingest.service import RagIngestService

TENANT_ID = uuid.uuid4()


class _FakeEmbeddingProvider:
    name = "openai"
    model = "text-embedding-3-small"
    dims = 4

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        self.calls.append(texts)
        vectors = [[float(i) * 0.1] * self.dims for i in range(len(texts))]
        return EmbeddingResult(
            vectors=vectors, model_used=self.model, dims=self.dims, latency_ms=12
        )


class _FakeStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def replace_document(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def _service(
    provider: _FakeEmbeddingProvider | None = None, store: _FakeStore | None = None
) -> tuple[RagIngestService, _FakeEmbeddingProvider, _FakeStore]:
    provider = provider or _FakeEmbeddingProvider()
    store = store or _FakeStore()
    service = RagIngestService(
        counter=TokenCounter(),
        embedding_provider=provider,  # type: ignore[arg-type]
        store=store,  # type: ignore[arg-type]
        child_tokens=50,
        parent_tokens=200,
        overlap_tokens=10,
    )
    return service, provider, store


def _doc(text: str, *, module: str = "docs", ref: str = "guide.md") -> SourceDocument:
    return SourceDocument(module=module, source_ref=ref, text=text)


class TestIngest:
    async def test_embeds_all_children_of_document_in_one_batch(self) -> None:
        text = "Alpha " * 200  # well over one 50-token child
        service, provider, store = _service()
        report = await service.ingest(tenant_id=TENANT_ID, documents=[_doc(text)])

        assert report.docs_processed == 1
        assert len(provider.calls) == 1  # one batch for the whole document
        assert len(store.calls) == 1
        call = store.calls[0]
        assert call["tenant_id"] == TENANT_ID
        assert call["module"] == "docs"
        assert call["source_ref"] == "guide.md"
        assert call["embedding_model"] == "text-embedding-3-small"
        assert call["dims"] == 4
        # Every parent carries exactly as many vectors as it has children.
        for parent, vectors in call["parents_and_vectors"]:
            assert isinstance(parent, ParentChunk)
            assert len(vectors) == len(parent.children)

    async def test_vectors_are_aligned_to_their_parents_in_order(self) -> None:
        text = "Beta " * 300
        service, provider, store = _service()
        await service.ingest(tenant_id=TENANT_ID, documents=[_doc(text)])

        call = store.calls[0]
        offset = 0
        for parent, vectors in call["parents_and_vectors"]:
            # Fake vectors are [float(i)*0.1]*dims for the flat child order;
            # slicing per parent yields the same values the repo will store.
            expected_start = [float(offset) * 0.1] * provider.dims
            assert vectors[0][0] == expected_start[0]
            offset += len(parent.children)

    async def test_empty_document_gives_skipped_tally_not_a_store_call(self) -> None:
        service, _provider, store = _service()
        report = await service.ingest(
            tenant_id=TENANT_ID,
            documents=[_doc("   \n  "), _doc("Real content here")],
        )
        assert report.docs_processed == 1
        assert report.docs_skipped_empty == 1
        assert len(store.calls) == 1

    async def test_report_counts_parents_children_and_tokens(self) -> None:
        text = "Gamma " * 400
        service, _provider, store = _service()
        report = await service.ingest(tenant_id=TENANT_ID, documents=[_doc(text)])

        call = store.calls[0]
        children_in_store = sum(len(p.children) for p, _ in call["parents_and_vectors"])
        assert report.parents == len(call["parents_and_vectors"])
        assert report.children == children_in_store
        assert report.tokens_embedded > 0
        assert report.dims == 4
        assert report.model_used == "text-embedding-3-small"
        assert report.total_latency_ms >= 12

    async def test_provider_count_mismatch_raises_typed_error(self) -> None:
        class MismatchedProvider(_FakeEmbeddingProvider):
            async def embed(self, texts: list[str]) -> EmbeddingResult:
                self.calls.append(texts)
                # Return one fewer vector than requested.
                vectors = [[0.1] * self.dims for _ in range(max(len(texts) - 1, 0))]
                return EmbeddingResult(
                    vectors=vectors, model_used=self.model, dims=self.dims, latency_ms=1
                )

        service, _provider, store = _service(provider=MismatchedProvider())
        with pytest.raises(AiInvalidResponseError):
            await service.ingest(tenant_id=TENANT_ID, documents=[_doc("Delta " * 200)])
        assert store.calls == []
