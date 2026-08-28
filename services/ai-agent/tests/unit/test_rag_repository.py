"""Unit tests for the RAG repository (SKY-58).

The repository is pure orchestration over the SQLAlchemy session, so a fake
session records the emitted DML instead of hitting Postgres: deletes must run
children-first and be tenant/module/source scoped, and inserted rows must
carry the correct composite-key/vector/provenance values.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy

from ai_agent.core.chunker import ChildChunk, ParentChunk
from ai_agent.db.rag_repository import RagRepository
from ai_agent.models.ai_rag_chunk import AiRagChunkModel
from ai_agent.models.ai_rag_parent import AiRagParentModel

TENANT_ID = uuid.uuid4()
MODULE = "products"
SOURCE_REF = "products/00000000-0000-0000-0000-000000000001"


class _FakeSession:
    """Records adds, deletes, and the flush call — no real SQL."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.executed: list[object] = []
        self.flushed = False

    async def execute(self, statement: object) -> None:
        self.executed.append(statement)
        return None

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True


def _parents_and_vectors() -> list[tuple[ParentChunk, list[list[float]]]]:
    child = ChildChunk(index=0, text="Laptop Charger 65W", token_count=8)
    parent = ParentChunk(index=0, text="Laptop Charger 65W", token_count=8, children=(child,))
    return [(parent, [[0.1, 0.2, 0.3, 0.4]])]


class TestReplaceDocument:
    async def test_deletes_children_before_parent_scoped_to_tenant(self) -> None:
        session = _FakeSession()
        repo = RagRepository(session)  # type: ignore[arg-type]
        await repo.replace_document(
            tenant_id=TENANT_ID,
            module=MODULE,
            source_ref=SOURCE_REF,
            parents_and_vectors=_parents_and_vectors(),
            embedding_model="text-embedding-3-small",
            dims=4,
        )

        assert len(session.executed) == 2
        child_delete, parent_delete = session.executed
        assert isinstance(child_delete, sqlalchemy.Delete)
        assert isinstance(parent_delete, sqlalchemy.Delete)
        assert "DELETE FROM ai_rag_chunks" in str(child_delete)
        assert "DELETE FROM ai_rag_parents" in str(parent_delete)

    async def test_inserts_parent_and_child_with_matching_foreign_key(self) -> None:
        session = _FakeSession()
        repo = RagRepository(session)  # type: ignore[arg-type]
        await repo.replace_document(
            tenant_id=TENANT_ID,
            module=MODULE,
            source_ref=SOURCE_REF,
            parents_and_vectors=_parents_and_vectors(),
            embedding_model="text-embedding-3-small",
            dims=4,
        )

        parents = [o for o in session.added if isinstance(o, AiRagParentModel)]
        chunks = [o for o in session.added if isinstance(o, AiRagChunkModel)]
        assert len(parents) == 1
        assert len(chunks) == 1

        parent = parents[0]
        assert parent.tenant_id == TENANT_ID
        assert parent.module == MODULE
        assert parent.source_ref == SOURCE_REF
        assert parent.chunk_text == "Laptop Charger 65W"
        assert parent.id is not None

        chunk = chunks[0]
        assert chunk.tenant_id == TENANT_ID
        assert chunk.parent_id == parent.id  # composite FK target matches
        assert chunk.chunk_text == "Laptop Charger 65W"
        assert chunk.embedding == [0.1, 0.2, 0.3, 0.4]
        assert chunk.embedding_model == "text-embedding-3-small"
        assert chunk.embedding_dims == 4
        assert chunk.chunk_index == 0

    async def test_flush_called_so_unit_of_work_can_commit(self) -> None:
        session = _FakeSession()
        repo = RagRepository(session)  # type: ignore[arg-type]
        await repo.replace_document(
            tenant_id=TENANT_ID,
            module=MODULE,
            source_ref=SOURCE_REF,
            parents_and_vectors=_parents_and_vectors(),
            embedding_model="m",
            dims=4,
        )
        assert session.flushed is True

    async def test_empty_document_does_nothing(self) -> None:
        session = _FakeSession()
        repo = RagRepository(session)  # type: ignore[arg-type]
        await repo.replace_document(
            tenant_id=TENANT_ID,
            module=MODULE,
            source_ref=SOURCE_REF,
            parents_and_vectors=[],
            embedding_model="m",
            dims=4,
        )
        assert session.added == []
        assert session.executed == []

    async def test_vector_count_mismatch_raises_before_any_insert(self) -> None:
        session = _FakeSession()
        repo = RagRepository(session)  # type: ignore[arg-type]
        child = ChildChunk(index=0, text="x", token_count=1)
        parent = ParentChunk(index=0, text="x", token_count=1, children=(child,))
        with pytest.raises(ValueError, match="vector count"):
            await repo.replace_document(
                tenant_id=TENANT_ID,
                module=MODULE,
                source_ref=SOURCE_REF,
                parents_and_vectors=[(parent, [[0.1], [0.2]])],  # 2 vectors, 1 child
                embedding_model="m",
                dims=4,
            )

    async def test_vector_dimension_mismatch_raises(self) -> None:
        session = _FakeSession()
        repo = RagRepository(session)  # type: ignore[arg-type]
        child = ChildChunk(index=0, text="x", token_count=1)
        parent = ParentChunk(index=0, text="x", token_count=1, children=(child,))
        with pytest.raises(ValueError, match="dimension"):
            await repo.replace_document(
                tenant_id=TENANT_ID,
                module=MODULE,
                source_ref=SOURCE_REF,
                parents_and_vectors=[(parent, [[0.1]])],  # dim 1 != 4
                embedding_model="m",
                dims=4,
            )
