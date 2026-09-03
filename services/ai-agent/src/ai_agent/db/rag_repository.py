"""Persistence for parent-child RAG documents (SKY-58).

``replace_document`` implements idempotent re-ingestion: it deletes the
existing rows for ``(tenant_id, module, source_ref)`` - children first, then
the parent (FK order) - and inserts the new parent plus its embedded children.
``--incremental`` and ``--full`` ingestion modes therefore converge to the
same final state; re-running a document is always safe.

Integrity is enforced by Postgres, not this layer: the chunk FK targets the
composite parent PK ``(tenant_id, id)``, and RLS (``current_tenant_id()``)
bounds every row to the tenant set on the session by the caller - the CLI
MUST populate :class:`TenantContext` before calling, or the deletes/writes
silently match no rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from ai_agent.models.ai_rag_chunk import AiRagChunkModel
from ai_agent.models.ai_rag_parent import AiRagParentModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ai_agent.core.chunker import ParentChunk


@dataclass(frozen=True, slots=True)
class ChunkHit:
    """One child chunk retrieved by vector similarity."""

    chunk_id: uuid.UUID
    parent_id: uuid.UUID
    source_ref: str
    module: str
    chunk_text: str
    chunk_index: int
    metadata_: dict[str, object]
    cosine_distance: float


@dataclass(frozen=True, slots=True)
class ParentRecord:
    """One parent chunk returned to the LLM for generation context."""

    parent_id: uuid.UUID
    source_ref: str
    module: str
    chunk_text: str
    metadata_: dict[str, object]


class RagRepository:
    """Tenant-scoped access to the RAG parent/chunk tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def replace_document(
        self,
        *,
        tenant_id: uuid.UUID,
        module: str,
        source_ref: str,
        parents_and_vectors: list[tuple[ParentChunk, list[list[float]]]],
        embedding_model: str,
        dims: int,
    ) -> None:
        """Replace one document's rows with the new parents and child vectors.

        Raises:
            ValueError: If child/vector counts or vector dimensions misalign.
        """
        if not parents_and_vectors:
            return

        # Children first: their FK to the parent must not dangle mid-delete.
        await self.session.execute(
            delete(AiRagChunkModel).where(
                AiRagChunkModel.tenant_id == tenant_id,
                AiRagChunkModel.module == module,
                AiRagChunkModel.source_ref == source_ref,
            )
        )
        await self.session.execute(
            delete(AiRagParentModel).where(
                AiRagParentModel.tenant_id == tenant_id,
                AiRagParentModel.module == module,
                AiRagParentModel.source_ref == source_ref,
            )
        )

        for parent, child_vectors in parents_and_vectors:
            if len(child_vectors) != len(parent.children):
                raise ValueError(
                    f"vector count does not match child chunk count for {module}/{source_ref}"
                )
            parent_id = uuid.uuid4()
            self.session.add(
                AiRagParentModel(
                    tenant_id=tenant_id,
                    id=parent_id,
                    source_ref=source_ref,
                    chunk_text=parent.text,
                    module=module,
                    metadata_={},
                )
            )
            for child, vector in zip(parent.children, child_vectors, strict=True):
                if len(vector) != dims:
                    raise ValueError(
                        f"vector dimension {len(vector)} != expected {dims} ({module}/{source_ref})"
                    )
                self.session.add(
                    AiRagChunkModel(
                        tenant_id=tenant_id,
                        id=uuid.uuid4(),
                        parent_id=parent_id,
                        source_ref=source_ref,
                        chunk_text=child.text,
                        embedding=vector,
                        module=module,
                        chunk_index=child.index,
                        metadata_={},
                        embedding_model=embedding_model,
                        embedding_dims=dims,
                    )
                )

        await self.session.flush()

    async def semantic_search(
        self,
        *,
        tenant_id: uuid.UUID,
        query_vector: list[float],
        top_k: int,
        module: str | None = None,
    ) -> list[ChunkHit]:
        """Cosine-similarity search over child chunks (ivfflat index).

        RLS keeps the rows tenant-scoped; the explicit ``tenant_id`` filter is
        defense in depth (and the optimizer's entry point into the index).
        """
        distance = AiRagChunkModel.embedding.cosine_distance(query_vector)
        stmt = (
            select(AiRagChunkModel, distance)
            .where(AiRagChunkModel.tenant_id == tenant_id)
            .order_by(distance)
            .limit(top_k)
        )
        if module:
            stmt = stmt.where(AiRagChunkModel.module == module)
        result = await self.session.execute(stmt)
        return [
            ChunkHit(
                chunk_id=row.id,
                parent_id=row.parent_id,
                source_ref=row.source_ref,
                module=row.module,
                chunk_text=row.chunk_text,
                chunk_index=row.chunk_index,
                metadata_=row.metadata_,
                cosine_distance=float(distance_value),
            )
            for row, distance_value in result.all()
        ]

    async def fetch_parents(
        self,
        *,
        tenant_id: uuid.UUID,
        parent_ids: list[uuid.UUID],
    ) -> list[ParentRecord]:
        """Fetch parent chunks by id (ordered like the input list)."""
        if not parent_ids:
            return []
        result = await self.session.execute(
            select(AiRagParentModel).where(
                AiRagParentModel.tenant_id == tenant_id,
                AiRagParentModel.id.in_(parent_ids),
            )
        )
        by_id = {row.id: row for row in result.scalars().all()}
        return [
            ParentRecord(
                parent_id=parent_id,
                source_ref=row.source_ref,
                module=row.module,
                chunk_text=row.chunk_text,
                metadata_=row.metadata_,
            )
            for parent_id in parent_ids
            if (row := by_id.get(parent_id)) is not None
        ]

    async def status_for_tenant(self, *, tenant_id: uuid.UUID) -> list[dict[str, object]]:
        """Per-module ingest stats for the /ai/rag/status endpoint."""
        parent_stats = await self.session.execute(
            select(
                AiRagParentModel.module,
                func.count(AiRagParentModel.id).label("parents"),
                func.count(func.distinct(AiRagParentModel.source_ref)).label("documents"),
                func.max(AiRagParentModel.created_at).label("last_ingested_at"),
            )
            .where(AiRagParentModel.tenant_id == tenant_id)
            .group_by(AiRagParentModel.module)
        )
        chunk_stats = await self.session.execute(
            select(
                AiRagChunkModel.module,
                func.count(AiRagChunkModel.id).label("children"),
            )
            .where(AiRagChunkModel.tenant_id == tenant_id)
            .group_by(AiRagChunkModel.module)
        )
        child_counts = {row[0]: row[1] for row in chunk_stats.all()}
        modules: list[dict[str, object]] = []
        for module, parents, documents, last_ingested_at in parent_stats.all():
            modules.append(
                {
                    "module": module,
                    "documents": documents,
                    "parents": parents,
                    "children": child_counts.get(module, 0),
                    "last_ingested_at": last_ingested_at,
                }
            )
        return modules
