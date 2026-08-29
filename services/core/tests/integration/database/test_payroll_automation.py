"""Payroll automation engine integration tests (HR-AUT-001, Commit 1).

Real Postgres + real migrations, driving :class:`PayrollAutomationService`
through its own session — the same path the in-process worker and the
``POST /ai/payroll/tick`` route use. Covers the acceptance scrub:

  * a full 50-employee run completes in well under 60s (claimed in chunks,
    resumed across ticks — per-item durable checkpoints);
  * an injected permanent failure (#27) is terminal — never re-claimed, never
    retried — the batch still closes ``completed`` with ``totals.failed=1``;
  * the claim is exactly-one-winner even under two overlapping transactions;
  * ``dry_run`` computes in memory but never writes entries or moves the run;
  * a transient failure burns one retry, gets re-claimed, and succeeds.

Skipped automatically when Postgres is unreachable (``migrated_schema``).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import date
from typing import Any

import pytest
from sqlalchemy import text

from core.api.deps import make_core_audit_service, make_payroll_service
from core.db.session import async_session_factory, engine
from core.features.hr.models.employee import EmployeeModel
from core.features.payroll.models.compensation import CompensationModel
from core.features.payroll.models.payroll_run import PayrollRunModel, PayrollRunStatus
from core.features.payroll.models.payroll_settings import PayrollSettingsModel
from core.features.payroll_automation.constants import BATCH_COMPLETED
from core.features.payroll_automation.repository import PostgresPayrollAutomationRepository
from core.features.payroll_automation.service import (
    PayrollAutomationService,
    PermanentBatchItemError,
)
from core.models.tenant import TenantModel

pytestmark = pytest.mark.integration

PERIOD_START = date(2026, 7, 1)
PERIOD_END = date(2026, 7, 31)
EMPLOYEE_COUNT = 50


@pytest.fixture(scope="module")
def payroll_batch_world(migrated_schema: None) -> dict[str, str]:
    """One tenant with 50 active compensated employees + a DRAFT run.

    Plain (sync) fixture: all writes run inside one ``asyncio.run()`` with the
    engine disposed inside, leaving a clean pool bound to each function-scoped
    test's own loop (the fixture discipline from ``test_hr_payroll``).
    """

    async def _setup() -> dict[str, str]:
        tenant_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        dry_run_id = str(uuid.uuid4())
        transient_id = str(uuid.uuid4())
        async with async_session_factory() as session:
            session.add(
                TenantModel(
                    id=uuid.UUID(tenant_id),
                    name="Payroll Automation Tenant",
                    slug=f"payroll-auto-{tenant_id[:8]}",
                    plan_tier="enterprise",
                    is_active=True,
                )
            )
            await session.flush()
            session.add(
                PayrollSettingsModel(
                    tenant_id=uuid.UUID(tenant_id),
                    default_currency="USD",
                    pf_rate=0,
                    tax_rate=0,
                )
            )
            for idx in range(1, EMPLOYEE_COUNT + 1):
                employee = EmployeeModel(
                    tenant_id=uuid.UUID(tenant_id),
                    id=uuid.uuid4(),
                    employee_number=f"EMP-{idx:04d}",
                    first_name=f"Emp{idx}",
                    last_name=f"Seed{idx}",
                    job_title="Engineer",
                    hire_date=date(2025, 1, 1),
                )
                session.add(employee)
                await session.flush()
                session.add(
                    CompensationModel(
                        tenant_id=uuid.UUID(tenant_id),
                        employee_id=employee.id,
                        monthly_salary=5000 + (idx % 10) * 500,
                        currency="USD",
                        effective_from=date(2025, 1, 1),
                    )
                )
            for run in (
                (run_id, "PR-AUTO-1", date(2026, 7, 1), date(2026, 7, 31)),
                (dry_run_id, "PR-AUTO-2", date(2026, 8, 1), date(2026, 8, 31)),
                (transient_id, "PR-AUTO-3", date(2026, 9, 1), date(2026, 9, 30)),
            ):
                session.add(
                    PayrollRunModel(
                        tenant_id=uuid.UUID(tenant_id),
                        id=uuid.UUID(run[0]),
                        run_code=run[1],
                        period_start=run[2],
                        period_end=run[3],
                        status=PayrollRunStatus.DRAFT,
                    )
                )
            await session.commit()
            await engine.dispose()
        return {
            "tenant_id": tenant_id,
            "run_id": run_id,
            "dry_run_id": dry_run_id,
            "transient_id": transient_id,
        }

    payroll_batch_world_data = asyncio.run(_setup())

    yield payroll_batch_world_data

    # Children first (composite FKs), then the tenant itself — mirroring the
    # erp_world teardown in test_hr_payroll.
    async def _teardown() -> None:
        tid = uuid.UUID(payroll_batch_world_data["tenant_id"])
        async with async_session_factory() as session:
            for table in (
                "ai_payroll_batch_items",
                "ai_payroll_batch_runs",
                "erp_payroll_entries",
                "erp_compensation",
                "erp_payroll_runs",
                "erp_payroll_settings",
                "erp_employees",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tid"),
                    {"tid": tid},
                )
            await session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
            await session.commit()
            await engine.dispose()

    asyncio.run(_teardown())


def _build_service(session: Any) -> tuple[PayrollAutomationService, Any]:
    """Build the engine on ``session``; return (service, payroll_service) so
    tests can inject faults into the compute seam."""
    payroll = make_payroll_service(session)
    service = PayrollAutomationService(
        repository=PostgresPayrollAutomationRepository(session),
        payroll=payroll,
        audit=make_core_audit_service(session),
        worker_id=f"it-{uuid.uuid4().hex[:8]}",
        max_retries=2,
        items_per_tick=10,
    )
    return service, payroll


async def _fault_once_compute_single(payroll: Any, *, target_number: str, exc: Exception) -> None:
    """Patch ``compute_single`` so the FIRST compute of `target_number` raises `exc`."""
    real = payroll.compute_single
    state = {"fired": False}

    async def _faulty(*, run_id: uuid.UUID, employee_id: uuid.UUID, tenant_id: uuid.UUID, persist: bool = True):
        if not state["fired"]:
            await payroll.get_run(run_id, tenant_id=tenant_id)
            roster = await payroll.active_employees(run_id, tenant_id=tenant_id)
            target = next(e for e in roster if e.employee_number == target_number)
            if employee_id == target.id:
                state["fired"] = True
                raise exc
        return await real(
            run_id=run_id,
            employee_id=employee_id,
            tenant_id=tenant_id,
            persist=persist,
        )

    payroll.compute_single = _faulty  # type: ignore[method-assign]


async def _drain_until_finished(
    service: PayrollAutomationService, *, timeout_s: float = 60.0
) -> list[bool]:
    """Call ``process_once`` in a loop until a batch finalizes (or timeout)."""
    started = time.monotonic()
    final_statuses: list[bool] = []
    while True:
        result = await service.process_once()
        if result.status_changed:
            final_statuses.append(True)
            break
        if result.batch_id is not None:
            final_statuses.append(False)
        if time.monotonic() - started > timeout_s:
            pytest.fail(f"batch did not finalize within {timeout_s}s")
        await asyncio.sleep(0)
    return final_statuses


async def _batch_row(session: Any, batch_id: uuid.UUID, tenant_id: uuid.UUID) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT batch.source, batch.source_ref, batch.status, batch.dry_run, "
                "batch.finished_at, batch.totals "
                "FROM ai_payroll_batch_runs batch "
                "WHERE batch.tenant_id = :tid AND batch.id = :bid"
            ),
            {"tid": tenant_id, "bid": batch_id},
        )
    ).one()
    return {
        "source": row.source,
        "source_ref": row.source_ref,
        "status": row.status,
        "dry_run": row.dry_run,
        "finished_at": row.finished_at,
        "totals": row.totals,
    }


async def _item_row(session: Any, *, tenant_id: uuid.UUID, employee_number: str) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                "SELECT it.status, it.retry_count, it.error_text "
                "FROM ai_payroll_batch_items it "
                "JOIN erp_employees e ON e.id = it.employee_id "
                "WHERE it.tenant_id = :tid AND e.employee_number = :num "
                "ORDER BY it.created_at DESC LIMIT 1"
            ),
            {"tid": tenant_id, "num": employee_number},
        )
    ).one()
    return {"status": row.status, "retry_count": row.retry_count, "error_text": row.error_text}


@pytest.mark.slow
async def test_full_50_employee_run_with_permanent_failure_finishes_under_60s(
    payroll_batch_world: dict[str, str],
) -> None:
    tenant_id = uuid.UUID(payroll_batch_world["tenant_id"])
    run_id = uuid.UUID(payroll_batch_world["run_id"])

    async with async_session_factory() as session:
        service, payroll = _build_service(session)
        await _fault_once_compute_single(
            payroll, target_number="EMP-0027", exc=PermanentBatchItemError("injected permanent failure")
        )

        started = time.monotonic()
        result = await service.enqueue(run_id=run_id, tenant_id=tenant_id)
        enqueue_elapsed = time.monotonic() - started
        assert enqueue_elapsed < 60.0
        assert result.employee_count == EMPLOYEE_COUNT, "all 50 roster employees become items"

        batch_id = result.batch.id

        # Idempotency: re-enqueueing the same run returns the same batch.
        again = await service.enqueue(run_id=run_id, tenant_id=tenant_id)
        assert again.batch.id == batch_id

        ticks = await _drain_until_finished(service)
        elapsed = time.monotonic() - started
        assert elapsed < 60.0, f"full 50-employee run took {elapsed:.1f}s (SLA is 60s)"
        assert len(ticks) > 1, "expected the run to be processed across several ticks (resume)"

        row = await _batch_row(session, batch_id, tenant_id)
        assert row["status"] == BATCH_COMPLETED
        assert row["finished_at"] is not None
        totals = row["totals"]
        assert totals == {
            "total": 50,
            "done": 49,
            "failed": 1,
            "skipped": 0,
            "retried": 0,
            **{k: totals[k] for k in ("gross", "net")},
        }, totals

        failed_item = await _item_row(session, tenant_id=tenant_id, employee_number="EMP-0027")
        assert failed_item["status"] == "failed"
        assert failed_item["retry_count"] == 2, "permanent failure must not burn retries"
        assert "injected permanent failure" in failed_item["error_text"]

        # The run finalized like a normal compute: status computed + 49 entries.
        run_status = (
            await session.execute(
                text("SELECT status FROM erp_payroll_runs WHERE id = :rid AND tenant_id = :tid"),
                {"rid": run_id, "tid": tenant_id},
            )
        ).scalar_one()
        assert run_status == PayrollRunStatus.COMPUTED.value
        entry_count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM erp_payroll_entries WHERE run_id = :rid AND tenant_id = :tid"
                ),
                {"rid": run_id, "tid": tenant_id},
            )
        ).scalar_one()
        assert entry_count == 49, "the permanently-failed employee must not have an entry"

        batch_rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM ai_payroll_batch_runs "
                    "WHERE tenant_id = :tid AND source = 'payroll_run' AND source_ref = :rid"
                ),
                {"tid": tenant_id, "rid": str(run_id)},
            )
        ).scalar_one()
        assert batch_rows == 1, "exactly one batch per (source, source_ref)"


async def test_concurrent_claims_are_exactly_one_winner(
    payroll_batch_world: dict[str, str],
) -> None:
    # Dedicated tenant so this test owns its claimable world. Purge any other
    # claimable batch first (a failed previous test may have left one queued;
    # the claim is global across tenants, so a stray batch would absorb the
    # second worker).
    race_tenant = uuid.UUID(payroll_batch_world["tenant_id"])

    async with async_session_factory() as purge_session:
        await purge_session.execute(text("DELETE FROM ai_payroll_batch_items"))
        await purge_session.execute(text("DELETE FROM ai_payroll_batch_runs"))
        await purge_session.commit()

    batch_id: uuid.UUID
    async with async_session_factory() as seed_session:
        repo = PostgresPayrollAutomationRepository(seed_session)
        batch = await repo.create_batch(
            tenant_id=race_tenant,
            source="payroll_run",
            source_ref="race-test",
            dry_run=False,
            totals={"total": 1, "done": 0, "failed": 0, "skipped": 0, "retried": 0},
        )
        batch_id = batch.id
        emp_id = (
            await seed_session.execute(
                text(
                    "SELECT id FROM erp_employees WHERE tenant_id = :tid "
                    "ORDER BY employee_number LIMIT 1"
                ),
                {"tid": race_tenant},
            )
        ).scalar_one()
        await repo.add_items(batch_id=batch.id, tenant_id=race_tenant, employee_ids=[emp_id])
        await seed_session.commit()

    # The core container runs an always-on payroll worker that claims the
    # (global) earliest queued batch every 0.25s against this same dev DB. Pin
    # OUR race batch under s1's transaction for the whole test: the live worker
    # and the second claimant both use SKIP LOCKED and must skip a row they
    # cannot lock, making this test deterministic.
    async with async_session_factory() as s1:
        await s1.execute(
            text("SELECT id FROM ai_payroll_batch_runs WHERE id = :bid FOR UPDATE"),
            {"bid": batch_id},
        )
        async with async_session_factory() as s2:
            repo1 = PostgresPayrollAutomationRepository(s1)
            repo2 = PostgresPayrollAutomationRepository(s2)

            first = await repo1.claim_next_item(
                batch_id=batch_id, tenant_id=race_tenant, max_retries=2
            )
            second = await repo2.claim_next_item(
                batch_id=batch_id, tenant_id=race_tenant, max_retries=2
            )
            assert (first is None) != (second is None), "exactly one item claim must win"
            assert first is not None and first.batch_id == batch_id
            item_row = (
                await s1.execute(
                    text("SELECT status FROM ai_payroll_batch_items WHERE batch_id = :bid"),
                    {"bid": batch_id},
                )
            ).scalar_one()
            assert item_row == "processing", "winner's item is in-flight"

            # Same one-winner invariant on THE SAME batch across two workers
            # (same claimant session keeps its row pin, so it is the winner).
            b_first = await repo1.claim_next_batch("worker-1")
            b_second = await repo2.claim_next_batch("worker-2")
            assert b_first is not None, "the pinned claimant must win its own batch"
            assert b_first.id == batch_id
            assert b_second is None, "exactly one batch claim must win"
            await s1.rollback()  # release pin + claims, batch back to queued

    # The claims were all rolled back, leaving this batch queued. Remove it so
    # it never absorbs the next test's (global) drain.
    async with async_session_factory() as cleanup:
        await cleanup.execute(text("DELETE FROM ai_payroll_batch_items"))
        await cleanup.execute(text("DELETE FROM ai_payroll_batch_runs"))
        await cleanup.commit()


@pytest.mark.slow
async def test_dry_run_finalizes_without_writing_entries_or_moving_run(
    payroll_batch_world: dict[str, str],
) -> None:
    tenant_id = uuid.UUID(payroll_batch_world["tenant_id"])
    run_id = uuid.UUID(payroll_batch_world["dry_run_id"])

    async with async_session_factory() as session:
        service, _payroll = _build_service(session)
        result = await service.enqueue(run_id=run_id, tenant_id=tenant_id, dry_run=True)
        batch_id = result.batch.id
        await _drain_until_finished(service)

        row = await _batch_row(session, batch_id, tenant_id)
        assert row["status"] == BATCH_COMPLETED
        assert row["dry_run"] is True
        assert row["totals"]["done"] == 50  # computed in memory, counted as done
        assert row["totals"]["failed"] == 0

        run_status = (
            await session.execute(
                text("SELECT status FROM erp_payroll_runs WHERE id = :rid AND tenant_id = :tid"),
                {"rid": run_id, "tid": tenant_id},
            )
        ).scalar_one()
        assert run_status == PayrollRunStatus.DRAFT.value, "dry-run must not move the run"
        entry_count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM erp_payroll_entries WHERE run_id = :rid AND tenant_id = :tid"
                ),
                {"rid": run_id, "tid": tenant_id},
            )
        ).scalar_one()
        assert entry_count == 0, "dry-run must not persist entries"


@pytest.mark.slow
async def test_transient_failure_retries_then_succeeds(
    payroll_batch_world: dict[str, str],
) -> None:
    tenant_id = uuid.UUID(payroll_batch_world["tenant_id"])
    run_id = uuid.UUID(payroll_batch_world["transient_id"])

    async with async_session_factory() as session:
        service, payroll = _build_service(session)
        await _fault_once_compute_single(
            payroll,
            target_number="EMP-0010",
            exc=RuntimeError("transient hiccup"),
        )
        result = await service.enqueue(run_id=run_id, tenant_id=tenant_id)
        batch_id = result.batch.id
        await _drain_until_finished(service)

        row = await _batch_row(session, batch_id, tenant_id)
        assert row["status"] == BATCH_COMPLETED
        totals = row["totals"]
        assert totals["done"] == 50, "retried item must eventually succeed"
        assert totals["failed"] == 0
        assert totals["retried"] == 1, totals

        item = await _item_row(session, tenant_id=tenant_id, employee_number="EMP-0010")
        assert item["status"] == "done"
        assert item["retry_count"] == 1, "one transient failure must burn exactly one retry"


__all__: list[str] = []
