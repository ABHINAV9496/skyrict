"""ReportRepository unit tests - fake async session, no database (RPT-DATA-001)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from core.features.reporting.repository import ReportRepository


class FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._rows)

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None


class FakeSession:
    """Record executed statements and serve canned results in FIFO order."""

    def __init__(self, results: list[list[Any]] | None = None) -> None:
        self.queue = list(results or [])
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.flushed = 0

    async def execute(self, stmt: Any) -> FakeResult:
        self.statements.append(stmt)
        rows = self.queue.pop(0) if self.queue else []
        return FakeResult(rows)

    def add(self, model: Any) -> None:
        self.added.append(model)

    async def flush(self) -> None:
        self.flushed += 1


def _definition(tenant_id: uuid.UUID, slug: str, is_active: bool = True) -> Any:
    model = type("Definition", (), {})()
    model.tenant_id = tenant_id
    model.slug = slug
    model.is_active = is_active
    return model


def _snapshot(
    tenant_id: uuid.UUID,
    definition_id: uuid.UUID,
    period: date,
    payload: list[dict[str, Any]],
) -> Any:
    model = type("Snapshot", (), {})()
    model.tenant_id = tenant_id
    model.definition_id = definition_id
    model.period = period
    model.payload = payload
    return model


class TestListDefinitions:
    @pytest.mark.asyncio
    async def test_returns_definitions_and_filters_tenant(self) -> None:
        tenant_id = uuid.uuid4()
        rows = [_definition(tenant_id, "pnl_by_period"), _definition(tenant_id, "ar_aging")]
        session = FakeSession(results=[rows])
        repo = ReportRepository(session=session)  # type: ignore[arg-type]

        result = await repo.list_active_definitions(tenant_id=tenant_id)

        assert result == rows
        assert len(session.statements) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_none_found(self) -> None:
        session = FakeSession(results=[[]])
        repo = ReportRepository(session=session)  # type: ignore[arg-type]

        result = await repo.list_active_definitions(tenant_id=uuid.uuid4())

        assert result == []


class TestGetDefinition:
    @pytest.mark.asyncio
    async def test_returns_row_when_found(self) -> None:
        tenant_id = uuid.uuid4()
        row = _definition(tenant_id, "pnl_by_period")
        session = FakeSession(results=[[row]])
        repo = ReportRepository(session=session)  # type: ignore[arg-type]

        result = await repo.get_definition(tenant_id=tenant_id, slug="pnl_by_period")

        assert result is row

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self) -> None:
        session = FakeSession(results=[[]])
        repo = ReportRepository(session=session)  # type: ignore[arg-type]

        result = await repo.get_definition(tenant_id=uuid.uuid4(), slug="missing")

        assert result is None


class TestSnapshotUpsert:
    @pytest.mark.asyncio
    async def test_inserts_new_snapshot_when_missing(self) -> None:
        tenant_id = uuid.uuid4()
        definition_id = uuid.uuid4()
        period = date(2026, 9, 1)
        payload = [{"account": "revenue", "total": "123.45"}]
        session = FakeSession(results=[[]])
        repo = ReportRepository(session=session)  # type: ignore[arg-type]

        result = await repo.upsert_snapshot(
            tenant_id=tenant_id,
            definition_id=definition_id,
            period=period,
            payload=payload,
        )

        assert result in session.added
        assert result.tenant_id == tenant_id
        assert result.definition_id == definition_id
        assert result.period == period
        assert result.payload == payload
        assert session.flushed == 1

    @pytest.mark.asyncio
    async def test_replaces_payload_when_snapshot_exists(self) -> None:
        tenant_id = uuid.uuid4()
        definition_id = uuid.uuid4()
        period = date(2026, 9, 1)
        existing = _snapshot(tenant_id, definition_id, period, [{"old": True}])
        session = FakeSession(results=[[existing]])
        repo = ReportRepository(session=session)  # type: ignore[arg-type]

        new_payload = [{"account": "expense", "total": "-9.00"}]
        result = await repo.upsert_snapshot(
            tenant_id=tenant_id,
            definition_id=definition_id,
            period=period,
            payload=new_payload,
        )

        assert result is existing
        assert existing.payload == new_payload
        assert session.added == []
        assert session.flushed == 1


class TestGetSnapshot:
    @pytest.mark.asyncio
    async def test_returns_row_when_found(self) -> None:
        tenant_id = uuid.uuid4()
        definition_id = uuid.uuid4()
        period = date(2026, 9, 1)
        row = _snapshot(tenant_id, definition_id, period, [{"x": 1}])
        session = FakeSession(results=[[row]])
        repo = ReportRepository(session=session)  # type: ignore[arg-type]

        result = await repo.get_snapshot(
            tenant_id=tenant_id, definition_id=definition_id, period=period
        )

        assert result is row

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self) -> None:
        session = FakeSession(results=[[]])
        repo = ReportRepository(session=session)  # type: ignore[arg-type]

        result = await repo.get_snapshot(
            tenant_id=uuid.uuid4(), definition_id=uuid.uuid4(), period=date(2026, 9, 1)
        )

        assert result is None
