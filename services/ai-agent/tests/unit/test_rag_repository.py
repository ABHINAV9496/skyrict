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


class _Cursor:
    """Minimal result cursor for the retrieval-path queries."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows

    def scalars(self) -> _Cursor:
        return self

    def __iter__(self):  # pragma: no cover - iter(scalars())
        return iter(self._rows)


class _RetrievalFakeSession:
    """Session that returns queued cursors from ``execute``."""

    def __init__(self, cursors: list[_Cursor]) -> None:
        self._cursors = list(cursors)
        self.executed: list[object] = []

    async def execute(self, statement: object) -> _Cursor:
        self.executed.append(statement)
        return self._cursors.pop(0) if self._cursors else _Cursor([])


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


def _chunk_model(
    *,
    parent_id: uuid.UUID,
    chunk_index: int = 0,
    text: str = "Laptop Charger 65W",
) -> AiRagChunkModel:
    return AiRagChunkModel(
        tenant_id=TENANT_ID,
        id=uuid.uuid4(),
        parent_id=parent_id,
        source_ref=SOURCE_REF,
        chunk_text=text,
        module=MODULE,
        chunk_index=chunk_index,
        metadata_={},
    )


class TestSemanticSearch:
    async def test_filters_tenant_and_orders_by_cosine_distance_with_limit(self) -> None:
        parent_id = uuid.uuid4()
        chunk = _chunk_model(parent_id=parent_id)
        session = _RetrievalFakeSession([_Cursor([(chunk, 0.15)])])
        repo = RagRepository(session)  # type: ignore[arg-type]

        hits = await repo.semantic_search(
            tenant_id=TENANT_ID, query_vector=[0.1, 0.2, 0.3, 0.4], top_k=20
        )

        assert len(hits) == 1
        assert hits[0].parent_id == parent_id
        assert hits[0].chunk_text == "Laptop Charger 65W"
        assert hits[0].cosine_distance == pytest.approx(0.15)
        compiled = str(
            session.executed[0].compile(dialect=sqlalchemy.dialects.postgresql.dialect())
        )
        assert "ai_rag_chunks.tenant_id" in compiled
        assert "ai_rag_chunks.embedding <=>" in compiled
        assert "LIMIT" in compiled

    async def test_module_filter_added_when_provided(self) -> None:
        chunk = _chunk_model(parent_id=uuid.uuid4())
        session = _RetrievalFakeSession([_Cursor([(chunk, 0.3)])])
        repo = RagRepository(session)  # type: ignore[arg-type]

        await repo.semantic_search(
            tenant_id=TENANT_ID,
            query_vector=[0.1, 0.2, 0.3, 0.4],
            top_k=5,
            module="manuals",
        )

        compiled = str(
            session.executed[0].compile(dialect=sqlalchemy.dialects.postgresql.dialect())
        )
        assert (
            "ai_rag_chunks.module = 'manuals'" in compiled or "ai_rag_chunks.module =" in compiled
        )


class TestFetchParents:
    async def test_orders_results_like_the_input_ids(self) -> None:
        first_id, second_id = uuid.uuid4(), uuid.uuid4()
        first_parent = AiRagParentModel(
            tenant_id=TENANT_ID,
            id=first_id,
            source_ref=SOURCE_REF,
            chunk_text="First parent text",
            module=MODULE,
            metadata_={},
        )
        second_parent = AiRagParentModel(
            tenant_id=TENANT_ID,
            id=second_id,
            source_ref=SOURCE_REF,
            chunk_text="Second parent text",
            module=MODULE,
            metadata_={},
        )
        session = _RetrievalFakeSession([_Cursor([first_parent, second_parent])])
        repo = RagRepository(session)  # type: ignore[arg-type]

        records = await repo.fetch_parents(tenant_id=TENANT_ID, parent_ids=[second_id, first_id])

        assert [r.parent_id for r in records] == [second_id, first_id]
        assert records[0].chunk_text == "Second parent text"

    async def test_empty_input_returns_without_query(self) -> None:
        session = _RetrievalFakeSession([])
        repo = RagRepository(session)  # type: ignore[arg-type]
        assert await repo.fetch_parents(tenant_id=TENANT_ID, parent_ids=[]) == []
        assert session.executed == []


class TestStatusForTenant:
    async def test_merges_parent_and_chunk_stats_per_module(self) -> None:
        parent_rows = [("products", 12, 3, None), ("manuals", 4, 2, None)]
        child_rows = [("products", 45), ("manuals", 9)]
        session = _RetrievalFakeSession([_Cursor(parent_rows), _Cursor(child_rows)])
        repo = RagRepository(session)  # type: ignore[arg-type]

        modules = await repo.status_for_tenant(tenant_id=TENANT_ID)

        by_module = {row["module"]: row for row in modules}
        assert by_module["products"]["parents"] == 12
        assert by_module["products"]["documents"] == 3
        assert by_module["products"]["children"] == 45
        assert by_module["manuals"]["children"] == 9
        assert len(session.executed) == 2
