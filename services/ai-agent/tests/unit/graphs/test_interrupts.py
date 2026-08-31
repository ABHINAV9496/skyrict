"""Unit tests for the agent_interrupts ledger (SKY-59).

The ledger's job: one row per paused tool call, lazy 24h auto-deny on stale
touch, and a non-pending row can NEVER be decided twice (the double-approval
hole closes here). Statement shapes are asserted by compiling against the
PostgreSQL dialect; the transition logic runs against a fake session.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects import postgresql

from ai_agent.graphs.interrupts import InterruptRepository
from ai_agent.models.agent_interrupt import AgentInterruptModel
from skyrict_common.exceptions import ConflictError, NotFoundError

TENANT_ID = uuid.uuid4()
RUN_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


class _FakeResult:
    def __init__(self, rows: list[object] | None = None, rowcount: int = 1) -> None:
        self._rows = rows or []
        self._rowcount = rowcount

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[object]:
        return self._rows

    def scalar_one_or_none(self) -> object | None:
        return self._rows[0] if self._rows else None

    @property
    def rowcount(self) -> int:
        return self._rowcount


class _FakeSession:
    def __init__(self, result: list[object] | None = None, rowcount: int = 1) -> None:
        self.result = result
        self.rowcount = rowcount
        self.executed: list[object] = []
        self.added: list[AgentInterruptModel] = []
        self.flushed = False

    async def execute(self, statement: object) -> _FakeResult:
        self.executed.append(statement)
        return _FakeResult(self.result, self.rowcount)

    def add(self, obj: AgentInterruptModel) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True


def _compile(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]


def _pending_row(*, past_due: bool = False) -> AgentInterruptModel:
    return AgentInterruptModel(
        tenant_id=TENANT_ID,
        id=uuid.uuid4(),
        graph_run_id=RUN_ID,
        agent_name="restock_advisor",
        tool="apply_suggestion",
        payload={"tool": "apply_suggestion", "required_permission": "erp.inventory.ai.approve"},
        status="pending",
        expires_at=datetime.now(tz=UTC) - timedelta(hours=1)
        if past_due
        else datetime.now(tz=UTC) + timedelta(hours=1),
        created_at=datetime.now(tz=UTC),
    )


class TestCreatePending:
    async def test_opens_a_pending_row_with_24h_window(self) -> None:
        session = _FakeSession()
        repo = InterruptRepository(session)  # type: ignore[arg-type]

        row = await repo.create_pending(
            tenant_id=TENANT_ID,
            graph_run_id=RUN_ID,
            agent_name="restock_advisor",
            tool="apply_suggestion",
            payload={"tool": "apply_suggestion"},
        )

        assert row.status == "pending"
        assert row.tenant_id == TENANT_ID
        assert row.graph_run_id == RUN_ID
        assert session.flushed is True
        assert session.added[0] is row
        # The unit layer carries the window so in-memory rows are comparable
        # immediately (the DB server default is the same +24h).
        remaining = row.expires_at - datetime.now(tz=UTC)
        assert timedelta(hours=23, minutes=59) < remaining <= timedelta(hours=24)

    async def test_select_scoped_to_tenant_and_pending(self) -> None:
        session = _FakeSession()
        repo = InterruptRepository(session)  # type: ignore[arg-type]

        await repo.list_pending(tenant_id=TENANT_ID)

        sql = _compile(session.executed[0])
        assert "agent_interrupts" in sql
        assert "agent_interrupts.tenant_id =" in sql
        assert "agent_interrupts.status =" in sql
        assert "expires_at" in sql  # oldest expiry first


class TestGetForDecision:
    async def test_returns_row_for_tenant(self) -> None:
        ledger = _pending_row()
        session = _FakeSession([ledger])
        repo = InterruptRepository(session)  # type: ignore[arg-type]

        found = await repo.get_for_decision(tenant_id=TENANT_ID, interrupt_id=ledger.id)

        assert found is ledger

    async def test_missing_row_raises_not_found(self) -> None:
        session = _FakeSession([])
        repo = InterruptRepository(session)  # type: ignore[arg-type]

        with pytest.raises(NotFoundError):
            await repo.get_for_decision(tenant_id=TENANT_ID, interrupt_id=uuid.uuid4())


class TestLazyExpiry:
    async def test_past_due_pending_auto_denies_without_decider(self) -> None:
        ledger = _pending_row(past_due=True)
        session = _FakeSession([ledger], rowcount=1)
        repo = InterruptRepository(session)  # type: ignore[arg-type]

        expired = await repo.expire_if_stale(ledger)

        assert expired is True
        assert ledger.status == "denied"
        assert ledger.decided_by is None  # no human decided — the clock did
        assert ledger.decided_at is not None

    async def test_fresh_pending_is_not_expired(self) -> None:
        ledger = _pending_row()
        session = _FakeSession([ledger])
        repo = InterruptRepository(session)  # type: ignore[arg-type]

        assert await repo.expire_if_stale(ledger) is False
        assert ledger.status == "pending"

    async def test_decided_row_is_not_expired(self) -> None:
        ledger = _pending_row(past_due=True)
        ledger.status = "approved"
        session = _FakeSession([ledger])
        repo = InterruptRepository(session)  # type: ignore[arg-type]

        assert await repo.expire_if_stale(ledger) is False
        assert ledger.status == "approved"


class TestRecordDecision:
    async def test_applies_decision_with_decider(self) -> None:
        ledger = _pending_row()
        session = _FakeSession([ledger], rowcount=1)
        repo = InterruptRepository(session)  # type: ignore[arg-type]

        await repo.record_decision(ledger, decision="approved", decided_by=USER_ID)

        assert ledger.status == "approved"
        assert ledger.decided_by == USER_ID
        assert ledger.decided_at is not None

    async def test_refuses_to_decide_a_decided_row(self) -> None:
        ledger = _pending_row()
        ledger.status = "approved"
        session = _FakeSession([ledger])
        repo = InterruptRepository(session)  # type: ignore[arg-type]

        with pytest.raises(ConflictError):
            await repo.record_decision(ledger, decision="denied", decided_by=USER_ID)

    async def test_update_is_guarded_by_pending_status(self) -> None:
        ledger = _pending_row()
        session = _FakeSession([ledger], rowcount=1)
        repo = InterruptRepository(session)  # type: ignore[arg-type]

        await repo.record_decision(ledger, decision="denied", decided_by=USER_ID)

        sql = _compile(session.executed[0])
        assert "agent_interrupts.status =" in sql
        assert "agent_interrupts.tenant_id =" in sql
        assert "agent_interrupts.id =" in sql
