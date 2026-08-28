"""Unit tests for the durable RAG query-cache repository (SKY-58).

Postgres-specific constructs (INSERT ... ON CONFLICT, RETURNING, JSONB) are
asserted by compiling the statements against the PostgreSQL dialect rather
than running a database — string-level verification of the conflict target
and expiry filter is the contract that matters here.
"""

from __future__ import annotations

import uuid

from sqlalchemy.dialects import postgresql

from ai_agent.db.query_cache_repository import QueryCacheRepository

TENANT_ID = uuid.uuid4()


class _Result:
    rowcount: int = 0

    def scalar_one(self) -> object:
        return object()

    def scalar_one_or_none(self) -> object | None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.executed: list[object] = []

    async def execute(self, statement: object) -> _Result:
        self.executed.append(statement)
        return _Result()

    async def flush(self) -> None:
        pass


def _compile(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]


class TestPut:
    async def test_insert_uses_tenant_scoped_unique_conflict_target(self) -> None:
        session = _FakeSession()
        repo = QueryCacheRepository(session)  # type: ignore[arg-type]
        await repo.put(
            tenant_id=TENANT_ID,
            query_hash="a" * 64,
            query_text="alpha beta",
            response={"data": [{"score": 1.0}]},
            ttl_seconds=3600,
        )

        assert len(session.executed) == 1
        sql = _compile(session.executed[0])
        assert "INSERT INTO ai_query_cache" in sql
        assert "ON CONFLICT" in sql
        assert "uq_ai_query_cache_tenant_hash" in sql
        assert "hit_count" in sql

    async def test_put_increments_hit_count_on_conflict(self) -> None:
        session = _FakeSession()
        repo = QueryCacheRepository(session)  # type: ignore[arg-type]
        await repo.put(
            tenant_id=TENANT_ID,
            query_hash="b" * 64,
            query_text="beta gamma",
            response={"data": []},
            ttl_seconds=60,
        )

        sql = _compile(session.executed[0])
        # DO UPDATE must refresh response/expiry and increment the counter
        # (NOT replace the row) — repeat queries stay one row per tenant+hash.
        assert "ai_query_cache.hit_count +" in sql
        assert "expires_at" in sql

    async def test_expiry_is_bound_as_a_parameter_not_sql_function(self) -> None:
        session = _FakeSession()
        repo = QueryCacheRepository(session)  # type: ignore[arg-type]
        await repo.put(
            tenant_id=TENANT_ID,
            query_hash="c" * 64,
            query_text="gamma delta",
            response={"data": []},
            ttl_seconds=60,
        )

        sql = _compile(session.executed[0])
        # Python-computed expiry keeps invalid SQL out of the WHERE/SET
        # clauses (func.make_interval named-args render as bad syntax).
        assert "make_interval" not in sql
        assert "now()" not in sql
        assert "expires_at" in sql


class TestGet:
    async def test_get_filters_live_rows_only(self) -> None:
        session = _FakeSession()
        repo = QueryCacheRepository(session)  # type: ignore[arg-type]
        await repo.get(tenant_id=TENANT_ID, query_hash="d" * 64)

        assert len(session.executed) == 1
        sql = _compile(session.executed[0])
        assert "SELECT ai_query_cache" in sql
        assert "expires_at >" in sql


class TestDeleteExpired:
    async def test_sweep_deletes_only_expired_rows(self) -> None:
        session = _FakeSession()
        repo = QueryCacheRepository(session)  # type: ignore[arg-type]
        deleted = await repo.delete_expired()

        assert deleted == 0
        assert len(session.executed) == 1
        sql = _compile(session.executed[0])
        assert "DELETE FROM ai_query_cache" in sql
        # Narrow index scan: expires_at is indexed, and the predicate is the
        # same boundary reads use (<= now() rather than a timestamp binding).
        assert "expires_at <=" in sql
        assert "now" in sql
