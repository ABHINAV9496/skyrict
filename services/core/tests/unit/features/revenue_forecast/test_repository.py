"""Unit tests for RevenueForecastRepository deal-health reads (SKY-91).

Regression guard for the CI failure where a core-only database (no
``ai_deal_health`` migration) made ``pipeline_by_month`` die with
``InFailedSQLTransactionError``: the absent-table query raised
``ProgrammingError`` and the session was never rolled back, so every later
query in the request aborted. The repository now probes the relation with
``to_regclass`` (never raises) and, for the probe-vs-query race, rolls back
before degrading - both paths must leave the session usable.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from sqlalchemy.exc import ProgrammingError

from core.features.revenue_forecast.repository import RevenueForecastRepository

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")


class _FakeResult:
    def __init__(self, *, scalar_value: object = None, rows: list[object] | None = None) -> None:
        self._scalar = scalar_value
        self._rows = rows or []

    def scalar(self) -> object:
        return self._scalar

    def all(self) -> list[object]:
        return self._rows


class _FakeSession:
    """Records every call the repository makes; none hits a real database."""

    def __init__(self, *, table_present: bool, rows: list[object] | None = None) -> None:
        self._table_present = table_present
        self._rows = rows or []
        self._fail_health = False
        self.probes = 0
        self.health_queries = 0
        self.rollbacks = 0

    async def execute(self, stmt: object) -> _FakeResult:
        if "to_regclass" in str(stmt):
            self.probes += 1
            return _FakeResult(scalar_value="ai_deal_health" if self._table_present else None)
        self.health_queries += 1
        if self._fail_health:
            raise ProgrammingError("SELECT ...", {}, Exception("relation does not exist"))
        return _FakeResult(rows=self._rows)

    async def rollback(self) -> None:
        self.rollbacks += 1

    def make_health_race(self) -> None:
        self._fail_health = True


async def test_absent_table_never_aborts_the_transaction() -> None:
    """Core-only DB: weighting degrades without any health query or rollback.

    Regression for the SKY-91 CI failure: this path used to raise
    ``ProgrammingError`` (table absent) and leave the session with an aborted
    transaction; the next query died with ``InFailedSQLTransactionError``.
    """
    session = _FakeSession(table_present=False)
    repository = RevenueForecastRepository(session)  # type: ignore[arg-type]

    result = await repository._deal_health_assessments(TENANT, [uuid.uuid4()])

    assert result == {}
    assert session.probes == 1
    assert session.health_queries == 0
    assert session.rollbacks == 0


async def test_empty_opportunity_ids_short_circuit_before_probing() -> None:
    session = _FakeSession(table_present=False)
    repository = RevenueForecastRepository(session)  # type: ignore[arg-type]

    result = await repository._deal_health_assessments(TENANT, [])

    assert result == {}
    assert session.probes == 0
    assert session.health_queries == 0
    assert session.rollbacks == 0


async def test_present_table_returns_latest_assessment_per_opportunity() -> None:
    opportunity = uuid.uuid4()
    session = _FakeSession(
        table_present=True,
        rows=[
            SimpleNamespace(opportunity_id=opportunity, health="red", confidence=0.8),
            SimpleNamespace(opportunity_id=opportunity, health="green", confidence=0.9),
        ],
    )
    repository = RevenueForecastRepository(session)  # type: ignore[arg-type]

    result = await repository._deal_health_assessments(TENANT, [opportunity])

    assert result == {opportunity: ("red", 0.8)}
    assert session.probes == 1
    assert session.health_queries == 1
    assert session.rollbacks == 0


async def test_probe_query_race_rolls_back_then_degrades() -> None:
    """Table dropped between the probe and the read: roll back, then degrade.

    The rollback is what keeps ``pipeline_by_month``'s later queries (e.g.
    ``_stage_conversion_rates``) from failing with ``InFailedSQLTransactionError``.
    """
    session = _FakeSession(table_present=True)
    session.make_health_race()
    repository = RevenueForecastRepository(session)  # type: ignore[arg-type]

    result = await repository._deal_health_assessments(TENANT, [uuid.uuid4()])

    assert result == {}
    assert session.probes == 1
    assert session.health_queries == 1
    assert session.rollbacks == 1
