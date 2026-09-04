"""RAG ingestion orchestrator (SKY-58) - load → chunk → embed → persist.

Pure feature-layer service: receives a loader's documents, chunk them with the
token counter, embeds all children of each document in ONE provider batch,
and hands parent/child pairs to an injected repository. Dependencies
(repository, embedding provider) come from the composition root exactly like
``RestockService`` - this module imports NO models and NO db layer, keeping
the ``Only repositories touch the database layer`` contract intact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from ai_agent.core.chunker import chunk_document
from ai_agent.core.exceptions import AiInvalidResponseError

if TYPE_CHECKING:
    import uuid

    from ai_agent.core.chunker import ParentChunk
    from ai_agent.core.embedding import EmbeddingProvider
    from ai_agent.core.token_counter import TokenCounter
    from ai_agent.features.rag.ingest.loader import SourceDocument


class RagDocumentStore(Protocol):
    """Structural contract satisfied by :class:`RagRepository`."""

    async def replace_document(
        self,
        *,
        tenant_id: uuid.UUID,
        module: str,
        source_ref: str,
        parents_and_vectors: list[tuple[ParentChunk, list[list[float]]]],
        embedding_model: str,
        dims: int,
    ) -> None: ...


@dataclass(slots=True)
class IngestReport:
    """Tally of one ingestion run for the CLI/operator (accumulates)."""

    docs_processed: int
    docs_skipped_empty: int
    parents: int
    children: int
    tokens_embedded: int
    total_latency_ms: int
    model_used: str
    dims: int
    errors: list[str] = field(default_factory=list)


class RagIngestService:
    """Chunk, embed, and persist one set of source documents."""

    def __init__(
        self,
        *,
        counter: TokenCounter,
        embedding_provider: EmbeddingProvider,
        store: RagDocumentStore,
        child_tokens: int = 400,
        parent_tokens: int = 2000,
        overlap_tokens: int = 60,
    ) -> None:
        self._counter = counter
        self._provider = embedding_provider
        self._store = store
        self._child_tokens = child_tokens
        self._parent_tokens = parent_tokens
        self._overlap_tokens = overlap_tokens

    async def ingest(
        self, *, tenant_id: uuid.UUID, documents: list[SourceDocument]
    ) -> IngestReport:
        """Process every document, replacing its existing rows when present.

        A document whose parent context outlives one embed call splits into
        multiple replace cycles; provider/model/dim provenance comes from the
        last successful embed of the run.
        """
        report = IngestReport(
            docs_processed=0,
            docs_skipped_empty=0,
            parents=0,
            children=0,
            tokens_embedded=0,
            total_latency_ms=0,
            model_used=self._provider.model,
            dims=self._provider.dims,
        )

        for doc in documents:
            parents = chunk_document(
                doc.text,
                counter=self._counter,
                child_tokens=self._child_tokens,
                parent_tokens=self._parent_tokens,
                overlap_tokens=self._overlap_tokens,
            )
            if not parents:
                report.docs_skipped_empty += 1
                continue

            child_texts = [c.text for parent in parents for c in parent.children]
            result = await self._provider.embed(child_texts)
            report.total_latency_ms += result.latency_ms
            if len(result.vectors) != len(child_texts):
                raise AiInvalidResponseError(
                    "Embedding provider returned a different number of vectors than requested"
                )

            parents_and_vectors = self._split_by_parent(parents, result.vectors)
            await self._store.replace_document(
                tenant_id=tenant_id,
                module=doc.module,
                source_ref=doc.source_ref,
                parents_and_vectors=parents_and_vectors,
                embedding_model=result.model_used,
                dims=result.dims,
            )

            report.docs_processed += 1
            report.parents += len(parents)
            report.children += sum(
                len(vectors) for _, vectors in parents_and_vectors
            )  # one vector (i.e. one child chunk) per parent entry
            report.tokens_embedded += sum(
                c.token_count for parent in parents for c in parent.children
            )
            report.model_used = result.model_used
            report.dims = result.dims

        return report

    @staticmethod
    def _split_by_parent(
        parents: list[ParentChunk], vectors: list[list[float]]
    ) -> list[tuple[ParentChunk, list[list[float]]]]:
        """Slice the flat vector batch back into per-parent allocations."""
        grouped: list[tuple[ParentChunk, list[list[float]]]] = []
        offset = 0
        for parent in parents:
            count = len(parent.children)
            grouped.append((parent, vectors[offset : offset + count]))
            offset += count
        return grouped
