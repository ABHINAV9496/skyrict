"""Persistence for parent-child RAG documents (SKY-58).

``replace_document`` implements idempotent re-ingestion: it deletes the
existing rows for ``(tenant_id, module, source_ref)`` — children first, then
the parent (FK order) — and inserts the new parent plus its embedded children.
``--incremental`` and ``--full`` ingestion modes therefore converge to the
same final state; re-running a document is always safe.

Integrity is enforced by Postgres, not this layer: the chunk FK targets the
composite parent PK ``(tenant_id, id)``, and RLS (``current_tenant_id()``)
bounds every row to the tenant set on the session by the caller — the CLI
MUST populate :class:`TenantContext` before calling, or the deletes/writes
silently match no rows.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import delete

from ai_agent.models.ai_rag_chunk import AiRagChunkModel
from ai_agent.models.ai_rag_parent import AiRagParentModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ai_agent.core.chunker import ParentChunk


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
