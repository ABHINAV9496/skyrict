"""Unit tests for the RAGAS eval-run repository (SKY-58).

String-level verification against the PostgreSQL dialect pins the INSERT
shape: RETURNING is needed because the runner prints the persisted run row's
id, and the four aggregate Decimal columns must reach the typed Numeric(5, 4)
columns.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.dialects import postgresql

from ai_agent.db.eval_runs_repository import EvalRunsRepository


class _Result:
    def scalar_one(self) -> object:
        return object()


class _FakeSession:
    def __init__(self) -> None:
        self.executed: list[object] = []

    async def execute(self, statement: object) -> _Result:
        self.executed.append(statement)
        return _Result()


def _compile(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]


class TestInsertRun:
    async def test_insert_returns_generated_row(self) -> None:
        session = _FakeSession()
        repo = EvalRunsRepository(session)  # type: ignore[arg-type]
        row = await repo.insert_run(
            metrics={"scores": [{"faithfulness": 0.9}]},
            passed=True,
            sample_count=24,
            faithfulness=Decimal("0.9000"),
            answer_relevancy=Decimal("0.8500"),
            context_precision=Decimal("0.8000"),
            context_recall=Decimal("0.7500"),
        )

        assert row is not None
        assert len(session.executed) == 1
        sql = _compile(session.executed[0])
        assert "INSERT INTO ai_eval_runs" in sql
        assert "RETURNING ai_eval_runs" in sql
        assert "faithfulness" in sql
        assert "context_recall" in sql
        assert "metrics" in sql
        assert "passed" in sql

    async def test_insert_allows_null_metric_columns(self) -> None:
        """A failed early run (e.g. no contexts) still records its row."""
        session = _FakeSession()
        repo = EvalRunsRepository(session)  # type: ignore[arg-type]
        await repo.insert_run(
            metrics={"error": "no contexts retrieved"},
            passed=False,
            sample_count=0,
            faithfulness=None,
            answer_relevancy=None,
            context_precision=None,
            context_recall=None,
        )

        sql = _compile(session.executed[0])
        assert "INSERT INTO ai_eval_runs" in sql
        assert "faithfulness" in sql
