"""Atomicity, concurrency, and event-emission invariants (HR-BE-002 §9.2).

Closes the two integration gaps the 0007 review flagged: the DoD's "concurrent
approve → one guard wins; concurrent compute → one wins; failed approval leaves
request pending and no movement" row, and the "events emitted only after commit
(failed transaction → no event)" row — both of which had no test at all.

The event half works by swapping ``core.events.producers._event_producer`` for a
recording producer (the phase-1 stub reads that module global on every publish),
so "emitted events" become observable instead of a structlog log line.

Why each test is shaped this way:

- ``test_concurrent_approve_single_request`` — the CAS guard
  (``transition_leave_status`` conditional UPDATE) must make exactly one of two
  racing approves win: one movement, one audit row, one ``hr.leave.approved``
  event; the loser emits nothing.
- ``test_concurrent_compute_idempotent`` — the run-status CAS
  (``transition_run_status`` conditional UPDATE) lets only one racing compute
  win the DRAFT→COMPUTED flip; the loser 409s instead of overwriting the
  winner. Entries stay exactly one per employee (``upsert_entries`` is
  ``ON CONFLICT (tenant, run, employee) DO UPDATE``), the run stays computed.
- ``test_approve_beyond_balance_no_event`` — the service-level Rule 2 breach
  raises BEFORE any write; the request stays pending, no movement, no event.
- ``test_duplicate_department_no_event`` — a DB unique violation surfaces at
  flush inside the service call, before the emit; no event for the loser.
- ``test_hire_with_cross_tenant_department_no_event`` — a composite-FK
  violation at flush (the first write) aborts the whole service call before any
  event; proves the "failed transaction → no event" invariant through a real
  DB failure, not a mock.
- ``test_concurrent_approve_cross_requests_invariant`` — the coupling invariant
  across concurrent approvals of DIFFERENT requests for the same employee:
  approved requests == approval movements == emitted events, and materialized
  balance == ledger sum. The balance-row lock (docs §4.3) serializes the writes,
  so when two requests together exceed the balance exactly one approves and the
  invariant holds deterministically — no longer an xfail.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from core.core import audit_events
from core.core.audit_events import HR_EMPLOYEE_CREATED, HR_LEAVE_APPROVED
from core.db.session import async_session_factory

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from httpx import AsyncClient

pytestmark = pytest.mark.integration

_BALANCE_ON_HIRE = 20
_OLYMPUS = "olympus"


@dataclass
class _RecordedEvent:
    topic: str
    event_type: str
    tenant_id: str
    metadata: dict[str, object]


class _RecordingProducer:
    """Drop-in stub for ``core.events.producers._event_producer`` that records."""

    def __init__(self) -> None:
        self.events: list[_RecordedEvent] = []

    def publish(self, topic: str, event: Any, *, key: str | None = None) -> None:
        self.events.append(
            _RecordedEvent(
                topic=topic,
                event_type=event.event_type,
                tenant_id=event.tenant_id,
                metadata=event.metadata,
            )
        )

    async def apublish(self, topic: str, event: Any, *, key: str | None = None) -> None:
        self.publish(topic, event, key=key)


@pytest.fixture
def recorded_events(monkeypatch) -> list[_RecordedEvent]:
    """Swap the process-wide producer for a recorder; restore after the test."""
    from core.events import producers

    recorder = _RecordingProducer()
    monkeypatch.setattr(producers, "_event_producer", recorder)
    return recorder.events


# ---------------------------------------------------------------------------
# Direct DB probes (owner bypasses RLS; TenantContext is empty in the test proc)
# ---------------------------------------------------------------------------


async def _scalar(sql: str, **params: Any) -> Any:
    async with async_session_factory() as session:
        result = await session.execute(text(sql), params)
        await session.commit()
        return result.scalar_one()


async def _row(sql: str, **params: Any) -> Any:
    async with async_session_factory() as session:
        result = await session.execute(text(sql), params)
        await session.commit()
        return result.one()


async def _settle(predicate: Callable[[], Awaitable[bool]], timeout: float = 5.0) -> bool:
    """Wait (polling) until ``predicate`` holds or the timeout elapses.

    ``get_db`` commits AFTER the response is sent, so a 200 can be observed
    before its transaction is durable; the probes below must read post-commit
    state or they would report phantom desyncs.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(0.05)
    return False


async def _approval_movement_count(tenant_id: str, request_id: str) -> int:
    return await _scalar(
        "SELECT count(*) FROM erp_leave_movements "
        "WHERE tenant_id = :t AND ref_type = 'approval' AND ref_id = :r",
        t=uuid.UUID(tenant_id),
        r=request_id,
    )


async def _audit_count(tenant_id: str, action: str, target: str) -> int:
    return await _scalar(
        "SELECT count(*) FROM core_audit_logs "
        "WHERE tenant_id = :t AND action = :a AND target = :target",
        t=uuid.UUID(tenant_id),
        a=action,
        target=target,
    )


async def _materialized_balance(tenant_id: str, employee_id: str) -> int:
    return await _scalar(
        "SELECT balance FROM erp_leave_balances "
        "WHERE tenant_id = :t AND employee_id = :e AND leave_type = 'annual'",
        t=uuid.UUID(tenant_id),
        e=uuid.UUID(employee_id),
    )


async def _ledger_sum(tenant_id: str, employee_id: str) -> int:
    return await _scalar(
        "SELECT COALESCE(SUM(qty), 0) FROM erp_leave_movements "
        "WHERE tenant_id = :t AND employee_id = :e AND leave_type = 'annual'",
        t=uuid.UUID(tenant_id),
        e=uuid.UUID(employee_id),
    )


async def _leave_request_status(tenant_id: str, request_id: str) -> str:
    return await _scalar(
        "SELECT status FROM erp_leave_requests WHERE tenant_id = :t AND id = :r",
        t=uuid.UUID(tenant_id),
        r=uuid.UUID(request_id),
    )


def _count_by_type(events: list[_RecordedEvent], event_type: str) -> int:
    return sum(1 for event in events if event.event_type == event_type)


# ---------------------------------------------------------------------------
# Setup helpers (mirror tests/integration/api/helpers.py)
# ---------------------------------------------------------------------------


async def _hire(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    hire_date: str = "2026-01-05",
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "first_name": "Race",
        "last_name": "Test",
        "job_title": "Engineer",
        "hire_date": hire_date,
    }
    if overrides.pop("no_salary", False) is False:
        payload["monthly_salary"] = "5000.00"
    payload.update(overrides)
    response = await client.post("/api/v1/hr/employees", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _create_leave_request(
    client: AsyncClient, headers: dict[str, str], employee_id: str, days: int
) -> str:
    start = f"2026-02-{1:02d}"
    end = f"2026-03-{days:02d}" if days > 28 else f"2026-02-{days:02d}"
    response = await client.post(
        "/api/v1/hr/leave/requests",
        json={
            "employee_id": employee_id,
            "leave_type": "annual",
            "start_date": start,
            "end_date": end,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


class TestConcurrentApprove:
    async def test_concurrent_approve_single_request(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
        recorded_events: list[_RecordedEvent],
    ) -> None:
        """Two racing approves of the SAME request: one guard wins."""
        tenant_id = integration_db["acme_id"]
        headers = tenant_headers(_OLYMPUS)
        employee = await _hire(client, headers)
        request_id = await _create_leave_request(client, headers, employee["id"], 3)

        results = await asyncio.gather(
            client.post(f"/api/v1/hr/leave/requests/{request_id}/approve", headers=headers),
            client.post(f"/api/v1/hr/leave/requests/{request_id}/approve", headers=headers),
        )
        assert [r.status_code for r in results] == [200, 200]

        assert await _leave_request_status(tenant_id, request_id) == "approved"
        # Exactly one approval movement, one audit row, one event — the loser
        # of the CAS guard wrote nothing and emitted nothing.
        assert await _approval_movement_count(tenant_id, request_id) == 1
        assert (
            await _audit_count(
                tenant_id, audit_events.HR_LEAVE_APPROVED, f"leave_request:{request_id}"
            )
            == 1
        )

        async def _event_flushed() -> bool:
            return _count_by_type(recorded_events, HR_LEAVE_APPROVED) == 1

        # Events flush asynchronously after commit (db/session.py after_commit).
        assert await _settle(_event_flushed), "leave.approved event not flushed after commit"
        assert await _materialized_balance(tenant_id, employee["id"]) == _BALANCE_ON_HIRE - 3
        assert await _ledger_sum(tenant_id, employee["id"]) == _BALANCE_ON_HIRE - 3

    async def test_concurrent_approve_cross_requests_invariant(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
        recorded_events: list[_RecordedEvent],
    ) -> None:
        """Coupling invariant across racing approves of different requests for
        the same employee: approvals == movements == events, and the materialized
        balance always equals the ledger sum.

        The two requests together (30 days) exceed the balance (20), so the
        balance-row lock (docs §4.3) must let exactly one approve through: the
        loser re-reads the committed ledger under the lock and the Rule 2 check
        rejects it (422). The coupled counters agree and the materialized
        balance never drifts from the ledger — deterministically, not by timing.
        """
        tenant_id = integration_db["acme_id"]
        headers = tenant_headers(_OLYMPUS)
        employee = await _hire(client, headers)
        request_a = await _create_leave_request(client, headers, employee["id"], 15)
        request_b = await _create_leave_request(client, headers, employee["id"], 15)

        results = await asyncio.gather(
            client.post(f"/api/v1/hr/leave/requests/{request_a}/approve", headers=headers),
            client.post(f"/api/v1/hr/leave/requests/{request_b}/approve", headers=headers),
        )

        approved = sum(1 for r in results if r.status_code == 200)

        # Wait for the winner's commit (get_db commits after the response).
        async def _movements_settled() -> bool:
            return (
                await _approval_movement_count(tenant_id, request_a)
                + await _approval_movement_count(tenant_id, request_b)
            ) == approved

        settled = await _settle(_movements_settled)
        assert settled, "approval transactions did not settle within timeout"

        movements = await _approval_movement_count(
            tenant_id, request_a
        ) + await _approval_movement_count(tenant_id, request_b)
        events = _count_by_type(recorded_events, HR_LEAVE_APPROVED)

        # The three coupled counters must agree, whatever the race outcome.
        assert movements == approved == events, (
            f"desync: {approved} approvals, {movements} movements, {events} events"
        )
        # Materialized balance must never drift from the ledger recompute.
        materialized = await _materialized_balance(tenant_id, employee["id"])
        ledger = await _ledger_sum(tenant_id, employee["id"])
        assert materialized == ledger, (
            f"stale materialized balance: {materialized} != ledger {ledger}"
        )
        assert ledger >= 0

    async def test_concurrent_approve_cross_requests_stress_balance_exact(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
        recorded_events: list[_RecordedEvent],
    ) -> None:
        """10 racing approvals (5 days each) against a 20-day balance: exactly
        4 win and 6 are rejected — if any pair raced incorrectly the ledger
        would go negative. The row lock serializes every approve, so the final
        materialized balance must equal SUM(ledger) == 0 EXACTLY (not just "no
        error raised"), and movements == events == approvals."""
        tenant_id = integration_db["acme_id"]
        headers = tenant_headers(_OLYMPUS)
        employee = await _hire(client, headers)
        request_ids = [
            await _create_leave_request(client, headers, employee["id"], 5) for _ in range(10)
        ]

        results = await asyncio.gather(
            *(
                client.post(f"/api/v1/hr/leave/requests/{request_id}/approve", headers=headers)
                for request_id in request_ids
            )
        )

        approved = sum(1 for r in results if r.status_code == 200)
        rejected = sum(1 for r in results if r.status_code == 422)
        assert (approved, rejected) == (4, 6), (
            "expected exactly 4 approvals / 6 rejections, got "
            f"{approved}/{rejected}: {[r.status_code for r in results]}"
        )

        async def _movements_settled() -> bool:
            return (
                await _scalar(
                    "SELECT count(*) FROM erp_leave_movements "
                    "WHERE tenant_id = :t AND employee_id = :e AND ref_type = 'approval'",
                    t=uuid.UUID(tenant_id),
                    e=uuid.UUID(employee["id"]),
                )
                == approved
            )

        assert await _settle(_movements_settled), "approval movements did not settle"

        async def _event_flushed() -> bool:
            return _count_by_type(recorded_events, HR_LEAVE_APPROVED) == approved

        assert await _settle(_event_flushed), "leave.approved events not flushed"
        assert await _materialized_balance(tenant_id, employee["id"]) == 0
        assert await _ledger_sum(tenant_id, employee["id"]) == 0


class TestConcurrentCompute:
    async def test_concurrent_compute_idempotent(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
    ) -> None:
        """Two racing computes of one run: entries overwrite, never duplicate."""
        tenant_id = integration_db["acme_id"]
        headers = tenant_headers(_OLYMPUS)
        await _hire(client, headers, hire_date="2026-01-01")

        created = await client.post(
            "/api/v1/payroll/runs",
            json={"period_start": "2026-01-01", "period_end": "2026-01-31"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["data"]["id"]

        results = await asyncio.gather(
            client.post(f"/api/v1/payroll/runs/{run_id}/compute", headers=headers),
            client.post(f"/api/v1/payroll/runs/{run_id}/compute", headers=headers),
        )
        # The run-status CAS means only one racing compute wins the DRAFT->
        # COMPUTED flip; the loser 409s. Under serialized scheduling both may
        # return 200 (a computed->computed recompute) — either way the run
        # must end computed with exactly one entry per employee.
        assert [r.status_code for r in results] in ([200, 200], [200, 409], [409, 200])

        status, total_gross = await _row(
            "SELECT status, total_gross FROM erp_payroll_runs WHERE tenant_id = :t AND id = :r",
            t=uuid.UUID(tenant_id),
            r=uuid.UUID(run_id),
        )
        assert status == "computed"
        assert str(total_gross) == "5000.0000"  # numeric(10,4) column scale
        entry_count = await _scalar(
            "SELECT count(*) FROM erp_payroll_entries WHERE tenant_id = :t AND run_id = :r",
            t=uuid.UUID(tenant_id),
            r=uuid.UUID(run_id),
        )
        assert entry_count == 1  # one employee → one entry, never two

    async def test_concurrent_compute_with_approval_no_deadlock(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
    ) -> None:
        """A multi-employee compute (fresh 2027 grants → acquires several balance
        row locks in employee_number order) racing a single-employee approve
        (exactly one row lock) must neither deadlock nor time out.

        Single-row lock holders can never complete a cycle, and compute's lock
        acquisition is a stable total order (LOCK-ORDERING CONTRACT, see
        compute_run and HrRepository.lock_leave_balance), so no deadlock is
        possible — this test proves it end to end.
        """
        tenant_id = integration_db["acme_id"]
        headers = tenant_headers(_OLYMPUS)
        # Hires accrue 2026 annual on hire; the 2027 grants below are FRESH, so
        # compute_run takes a balance-row lock for every employee it accrues.
        employees = [await _hire(client, headers) for _ in range(3)]
        approve_target = employees[1]

        created = await client.post(
            "/api/v1/payroll/runs",
            json={"period_start": "2027-01-01", "period_end": "2027-01-31"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["data"]["id"]
        request_id = await _create_leave_request(client, headers, approve_target["id"], 5)

        results = await asyncio.gather(
            client.post(f"/api/v1/payroll/runs/{run_id}/compute", headers=headers),
            client.post(f"/api/v1/hr/leave/requests/{request_id}/approve", headers=headers),
        )
        assert results[0].status_code == 200, results[0].text
        assert results[1].status_code == 200, results[1].text

        (status,) = await _row(
            "SELECT status FROM erp_payroll_runs WHERE tenant_id = :t AND id = :r",
            t=uuid.UUID(tenant_id),
            r=uuid.UUID(run_id),
        )
        assert status == "computed"

        async def _grants_settled() -> bool:
            return (
                await _scalar(
                    "SELECT count(*) FROM erp_leave_movements "
                    "WHERE tenant_id = :t AND ref_type = 'annual_accrual' AND ref_id = '2027'",
                    t=uuid.UUID(tenant_id),
                )
                == 3
            )

        assert await _settle(_grants_settled), "2027 grants did not settle"

        # The approve deducted exactly once and balance still equals the ledger.
        assert (
            await _scalar(
                "SELECT count(*) FROM erp_leave_movements "
                "WHERE tenant_id = :t AND ref_type = 'approval' AND ref_id = :r",
                t=uuid.UUID(tenant_id),
                r=request_id,
            )
            == 1
        )
        materialized = await _materialized_balance(tenant_id, approve_target["id"])
        ledger = await _ledger_sum(tenant_id, approve_target["id"])
        assert materialized == ledger >= 0


class TestConcurrentAccrual:
    """Rule 4 idempotency under concurrency (probe → row-lock → re-probe)."""

    async def test_concurrent_first_grant_single_movement(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
    ) -> None:
        """Two racing FIRST-grant accruals of the same (employee, year): the
        probe → lock → re-probe in accrue_leave_movement means exactly ONE grant
        movement is written. This fails the moment the re-probe under the lock
        is skipped (two grants would be written and balance would diverge)."""
        tenant_id = integration_db["acme_id"]
        headers = tenant_headers(_OLYMPUS)
        employee = await _hire(client, headers)

        results = await asyncio.gather(
            client.post(
                "/api/v1/hr/leave/accrue",
                json={"employee_id": employee["id"], "leave_type": "annual", "leave_year": 2027},
                headers=headers,
            ),
            client.post(
                "/api/v1/hr/leave/accrue",
                json={"employee_id": employee["id"], "leave_type": "annual", "leave_year": 2027},
                headers=headers,
            ),
        )
        assert [r.status_code for r in results] == [200, 200]

        async def _grant_settled() -> bool:
            return (
                await _scalar(
                    "SELECT count(*) FROM erp_leave_movements "
                    "WHERE tenant_id = :t AND employee_id = :e "
                    "AND ref_type = 'annual_accrual' AND ref_id = '2027'",
                    t=uuid.UUID(tenant_id),
                    e=uuid.UUID(employee["id"]),
                )
                == 1
            )

        assert await _settle(_grant_settled), "expected exactly one 2027 grant movement"
        assert await _materialized_balance(tenant_id, employee["id"]) == await _ledger_sum(
            tenant_id, employee["id"]
        )


class TestNoEventOnFailedTransaction:
    async def test_approve_beyond_balance_no_event(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
        recorded_events: list[_RecordedEvent],
    ) -> None:
        """Rule 2 service breach: rejected before any write — pending, no movement, no event."""
        tenant_id = integration_db["acme_id"]
        headers = tenant_headers(_OLYMPUS)
        employee = await _hire(client, headers)
        request_id = await _create_leave_request(client, headers, employee["id"], 30)

        approved = await client.post(
            f"/api/v1/hr/leave/requests/{request_id}/approve", headers=headers
        )
        assert approved.status_code == 422
        assert approved.json()["type"].endswith("/leave-balance-exceeded")

        assert await _leave_request_status(tenant_id, request_id) == "pending"
        assert await _approval_movement_count(tenant_id, request_id) == 0
        assert _count_by_type(recorded_events, HR_LEAVE_APPROVED) == 0
        assert await _materialized_balance(tenant_id, employee["id"]) == _BALANCE_ON_HIRE

    async def test_duplicate_department_no_event(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        recorded_events: list[_RecordedEvent],
    ) -> None:
        """Unique violation at flush: the second create emits nothing."""
        headers = tenant_headers(_OLYMPUS)
        first = await client.post("/api/v1/hr/departments", json={"name": "Dev"}, headers=headers)
        assert first.status_code == 201, first.text

        duplicate = await client.post(
            "/api/v1/hr/departments", json={"name": "Dev"}, headers=headers
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["type"].endswith("/duplicate-record")
        # Only the first create emitted.
        assert _count_by_type(recorded_events, "hr.department.created") == 1

    async def test_hire_with_cross_tenant_department_no_event(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
        recorded_events: list[_RecordedEvent],
    ) -> None:
        """Composite-FK violation on the FIRST write aborts before any event."""
        tenant_id = integration_db["acme_id"]
        olympus = tenant_headers(_OLYMPUS)
        globex = tenant_headers("globex")

        department = await client.post(
            "/api/v1/hr/departments", json={"name": "Globex Dept"}, headers=globex
        )
        assert department.status_code == 201, department.text
        foreign_department_id = department.json()["data"]["id"]

        response = await client.post(
            "/api/v1/hr/employees",
            json={
                "first_name": "Ghost",
                "last_name": "Row",
                "job_title": "Engineer",
                "hire_date": "2026-01-05",
                "monthly_salary": "5000.00",
                "department_id": foreign_department_id,
            },
            headers=olympus,
        )
        assert response.status_code == 500

        # The failed transaction left nothing behind and emitted nothing.
        assert _count_by_type(recorded_events, HR_EMPLOYEE_CREATED) == 0
        ghost_count = await _scalar(
            "SELECT count(*) FROM erp_employees WHERE tenant_id = :t AND first_name = 'Ghost'",
            t=uuid.UUID(tenant_id),
        )
        assert ghost_count == 0


class TestPostEmitPreCommitFailure:
    """An event that was ALREADY buffered (emit succeeded) must still vanish
    if the transaction fails at COMMIT — the after_rollback listener discards
    the buffer, so a failed write can never be observed through an event."""

    async def test_buffered_event_discarded_when_commit_fails(
        self,
        migrated_schema: None,
        recorded_events: list[_RecordedEvent],
    ) -> None:
        from core.events import producers
        from core.events.producers import (
            buffered_events,
            clear_event_buffer,
            flush_events,
            start_event_buffer,
        )
        from skyrict_events.base import BaseEvent

        start_event_buffer()
        try:
            async with async_session_factory() as session:
                await producers.apublish(
                    "hr.leave.cancelled",
                    BaseEvent(
                        event_type="hr.leave.cancelled",
                        tenant_id=str(uuid.uuid4()),
                        metadata={},
                    ),
                )
                assert len(buffered_events()) == 1

                # A DB failure AFTER the emit (FK violation on a bogus tenant)
                # aborts the transaction before it can commit.
                with pytest.raises(SQLAlchemyError):
                    await session.execute(
                        text(
                            "INSERT INTO public.erp_leave_movements "
                            "(tenant_id, id, employee_id, leave_type, qty, ref_type, ref_id) "
                            "VALUES (:tenant_id, :id, :employee_id, 'annual', 1, "
                            "'manual_adjustment', NULL)"
                        ),
                        {
                            "tenant_id": uuid.UUID("00000000-0000-0000-0000-000000000000"),
                            "id": uuid.uuid4(),
                            "employee_id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
                        },
                    )
                await session.rollback()

            # after_rollback discarded the buffer; nothing was published.
            assert buffered_events() == []
            await flush_events()
            assert recorded_events == []
        finally:
            clear_event_buffer()
