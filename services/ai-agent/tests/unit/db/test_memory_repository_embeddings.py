"""Unit tests for the memory repository embedding recall paths (SKY-100).

Uses a fake session that records executed statements so the cosine-first
recall SQL (``embedding <=> :vec``, ``embedding IS NOT NULL``) and the
trigram/recency fallbacks can be asserted against the PostgreSQL dialect
without a live database. Store paths assert the row objects carry the
embedding metadata written by ``MemoryService``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from ai_agent.db.memory_repository import MemoryRepository
from ai_agent.models.ai_episodic_memory import AiEpisodicMemoryModel
from ai_agent.models.ai_semantic_memory import AiSemanticMemoryModel

TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
NOW = datetime.now(UTC)


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _Scalars:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _FakeSession:
    """Returns queued results per execute and records compiled statements."""

    def __init__(self, results: list[_Result] | None = None) -> None:
        self._results = list(results or [])
        self.executed: list[object] = []
        self.added: list[object] = []

    async def execute(self, statement: object) -> _Result:
        self.executed.append(statement)
        if self._results:
            return self._results.pop(0)
        return _Result([])

    async def flush(self) -> None:
        pass

    def add(self, row: object) -> None:
        self.added.append(row)


def _compile(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]


def _episodic_row(*, query: str = "what is on hand?", summary: str = "42 units") -> SimpleNamespace:
    return SimpleNamespace(
        query_text=query,
        response_summary=summary,
        created_at=NOW,
    )


def _semantic_row(
    *,
    fact: str = "Prefers weekly check-ins",
    category: str = "preference",
) -> SimpleNamespace:
    return SimpleNamespace(
        fact=fact,
        category=category,
        confidence=0.9,
        entity_type=None,
    )


class TestStoreEpisodicWithEmbedding:
    async def test_writes_embedding_metadata_when_provided(self) -> None:
        session = _FakeSession()
        repo = MemoryRepository(session)  # type: ignore[arg-type]
        vector = [0.1] * 768

        await repo.store_episodic(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            query_text="query",
            response_summary="summary",
            embedding=vector,
            embedding_model="text-embedding-3-small",
        )

        (row,) = session.added
        assert isinstance(row, AiEpisodicMemoryModel)
        assert row.embedding == vector
        assert row.embedding_model == "text-embedding-3-small"
        assert row.embedding_dims == 768

    async def test_leaves_embedding_null_when_omitted(self) -> None:
        session = _FakeSession()
        repo = MemoryRepository(session)  # type: ignore[arg-type]

        await repo.store_episodic(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            query_text="query",
            response_summary="summary",
        )

        (row,) = session.added
        assert isinstance(row, AiEpisodicMemoryModel)
        assert row.embedding is None
        assert row.embedding_model is None
        assert row.embedding_dims is None


class TestStoreSemanticFactsWithEmbedding:
    async def test_writes_embeddings_when_provided(self) -> None:
        session = _FakeSession()
        repo = MemoryRepository(session)  # type: ignore[arg-type]
        facts = [{"fact": "A", "category": "preference"}, {"fact": "B", "category": "context"}]
        vectors = [[0.1] * 768, [0.2] * 768]

        await repo.store_semantic_facts(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            facts=facts,
            embeddings=vectors,
            embedding_model="text-embedding-3-small",
        )

        rows: list[AiSemanticMemoryModel] = [
            r for r in session.added if isinstance(r, AiSemanticMemoryModel)
        ]
        assert len(rows) == 2
        assert rows[0].embedding == vectors[0]
        assert rows[1].embedding == vectors[1]
        assert rows[0].embedding_model == "text-embedding-3-small"
        assert rows[0].embedding_dims == 768

    async def test_leaves_embedding_null_when_omitted(self) -> None:
        session = _FakeSession()
        repo = MemoryRepository(session)  # type: ignore[arg-type]
        facts = [{"fact": "A", "category": "preference"}]

        await repo.store_semantic_facts(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            facts=facts,
        )

        (row,) = [r for r in session.added if isinstance(r, AiSemanticMemoryModel)]
        assert row.embedding is None
        assert row.embedding_model is None
        assert row.embedding_dims is None


class TestRecallEpisodic:
    async def test_cosine_first_uses_embedding_distance_and_nulls_filter(self) -> None:
        rows = [_episodic_row()]
        session = _FakeSession([_Result(rows)])
        repo = MemoryRepository(session)  # type: ignore[arg-type]

        result = await repo.recall_episodic(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            query="query",
            query_embedding=[0.5] * 768,
        )

        sql = _compile(session.executed[0])
        assert "ai_episodic_memory" in sql
        assert "embedding <=> %(embedding_1)s" in sql
        assert "embedding IS NOT NULL" in sql
        assert "ORDER BY ai_episodic_memory.embedding <=> %(embedding_1)s" in sql
        assert result == [
            {
                "query": rows[0].query_text,
                "summary": rows[0].response_summary,
                "created_at": NOW.isoformat(),
            }
        ]

    async def test_cosine_returns_none_on_missing_query_embedding(self) -> None:
        """No query embedding => the repository never compiles the vector query."""
        session = _FakeSession([_Result([])])
        repo = MemoryRepository(session)  # type: ignore[arg-type]

        await repo.recall_episodic(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            query="query",
        )

        sql = _compile(session.executed[0])
        assert "similarity(" in sql
        assert "<=>" not in sql

    async def test_cosine_empty_falls_through_to_trigram(self) -> None:
        """No embedded rows yet => cosine returns no rows, trigram is asked."""
        session = _FakeSession([_Result([]), _Result([_episodic_row()])])
        repo = MemoryRepository(session)  # type: ignore[arg-type]

        result = await repo.recall_episodic(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            query="query",
            query_embedding=[0.5] * 768,
        )

        assert len(session.executed) == 2
        sql = _compile(session.executed[1])
        assert "similarity(query_text, %(query)s) AS sim" in sql
        assert result  # trigram row surfaces

    async def test_cosine_exception_falls_through_to_trigram(self) -> None:
        class _ExplodingSession(_FakeSession):
            async def execute(self, statement: object) -> _Result:
                self.executed.append(statement)
                # Only the first (cosine) call explodes - let trigram succeed.
                if len(self.executed) == 1:
                    raise RuntimeError("pgvector unavailable")
                return _Result([_episodic_row()])

        session = _ExplodingSession()
        repo = MemoryRepository(session)  # type: ignore[arg-type]

        result = await repo.recall_episodic(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            query="query",
            query_embedding=[0.5] * 768,
        )

        assert len(session.executed) == 2
        assert "similarity(" in _compile(session.executed[1])
        assert result


class TestRecallSemantic:
    async def test_cosine_first_uses_embedding_distance_and_nulls_filter(self) -> None:
        rows = [_semantic_row()]
        session = _FakeSession([_Result(rows)])
        repo = MemoryRepository(session)  # type: ignore[arg-type]

        result = await repo.recall_semantic(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            query="query",
            query_embedding=[0.5] * 768,
        )

        sql = _compile(session.executed[0])
        assert "ai_semantic_memory" in sql
        assert "embedding <=> %(embedding_1)s" in sql
        assert "embedding IS NOT NULL" in sql
        assert result == [
            {
                "fact": rows[0].fact,
                "category": rows[0].category,
                "confidence": rows[0].confidence,
                "entity_type": rows[0].entity_type,
            }
        ]

    async def test_cosine_empty_falls_through_to_trigram(self) -> None:
        session = _FakeSession([_Result([]), _Result([_semantic_row()])])
        repo = MemoryRepository(session)  # type: ignore[arg-type]

        result = await repo.recall_semantic(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            query="query",
            query_embedding=[0.5] * 768,
        )

        assert len(session.executed) == 2
        sql = _compile(session.executed[1])
        assert "similarity(fact, %(query)s) AS sim" in sql
        assert result
