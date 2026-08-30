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
import dataclasses
import time
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text

from core.api.deps import make_core_audit_service, make_payroll_service
from core.db.session import async_session_factory, engine
from core.features.hr.models.employee import EmployeeModel
from core.features.payroll.models.benefits import (
    BenefitElectionModel,
    BenefitPlanModel,
)
from core.features.payroll.models.compensation import CompensationModel
from core.features.payroll.models.payroll_run import PayrollRunModel, PayrollRunStatus
from core.features.payroll.models.payroll_settings import PayrollSettingsModel
from core.features.payroll_automation.constants import BATCH_COMPLETED
from core.features.payroll_automation.repository import PostgresPayrollAutomationRepository
from core.features.payroll_automation.service import (
    PayrollAutomationService,
    PermanentBatchItemError,
)
from core.models.core_role import CoreRoleModel
from core.models.core_user_role import CoreUserRoleModel
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


def _build_service(
    session: Any, *, worker_id: str | None = None
) -> tuple[PayrollAutomationService, Any]:
    """Build the engine on ``session``; return (service, payroll_service) so
    tests can inject faults into the compute seam. ``worker_id`` pins the
    worker so fault-injection tests can deterministically claim their batch
    before the always-on dev worker polls it."""
    payroll = make_payroll_service(session)
    service = PayrollAutomationService(
        repository=PostgresPayrollAutomationRepository(session),
        payroll=payroll,
        audit=make_core_audit_service(session),
        worker_id=worker_id or f"it-{uuid.uuid4().hex[:8]}",
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
    service: PayrollAutomationService,
    session: Any,
    *,
    batch_id: uuid.UUID,
    timeout_s: float = 60.0,
) -> bool:
    """Drive ``process_once`` until the batch finalizes (or timeout).

    The dev stack runs an always-on core worker claiming the (global) earliest
    queued batch every 0.25s. Health-check finishes the batch under its own
    worker id, which the test worker cannot resume — so on top of driving our
    own ticks we poll the batch's DB row and stop as soon as it is terminal.
    Returns whether the batch reached a terminal status.
    """
    terminal = {"completed", "failed", "aborted"}
    started = time.monotonic()
    while True:
        result = await service.process_once()
        if result.status_changed:
            return True
        if time.monotonic() - started > timeout_s:
            pytest.fail(f"batch did not finalize within {timeout_s}s")
        status = (
            await session.execute(
                text("SELECT status FROM ai_payroll_batch_runs WHERE id = :bid"),
                {"bid": batch_id},
            )
        ).scalar_one_or_none()
        if status is not None and status in terminal:
            return True
        await asyncio.sleep(0)


FIXTURE_WORKER = "it-deterministic"


async def _claim_batch_for_this_worker(
    session: Any, *, expected_batch_id: uuid.UUID
) -> None:
    """Claim the just-created batch under THIS test worker before the always-on
    dev worker's 0.25s poll can take it — pin-first, matching the concurrency
    test's discipline. The claim is committed here; the service is built with
    the same worker id so its ticks resume this batch."""
    repo = PostgresPayrollAutomationRepository(session)
    claimed = await repo.claim_next_batch(FIXTURE_WORKER)
    await session.commit()
    assert claimed is not None and claimed.id == expected_batch_id


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
        service, payroll = _build_service(session, worker_id=FIXTURE_WORKER)
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

        # Pin the batch to this worker so the injected fault actually fires here
        # (the always-on dev worker would otherwise compute it cleanly).
        await _claim_batch_for_this_worker(session, expected_batch_id=batch_id)

        ticks = await _drain_until_finished(service, session, batch_id=batch_id)
        elapsed = time.monotonic() - started
        assert elapsed < 60.0, f"full 50-employee run took {elapsed:.1f}s (SLA is 60s)"
        assert ticks, "batch never returned through this worker"

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
        await _drain_until_finished(service, session, batch_id=batch_id)

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
        service, payroll = _build_service(session, worker_id=FIXTURE_WORKER)
        await _fault_once_compute_single(
            payroll,
            target_number="EMP-0010",
            exc=RuntimeError("transient hiccup"),
        )
        result = await service.enqueue(run_id=run_id, tenant_id=tenant_id)
        batch_id = result.batch.id
        await _claim_batch_for_this_worker(session, expected_batch_id=batch_id)
        await _drain_until_finished(service, session, batch_id=batch_id)

        row = await _batch_row(session, batch_id, tenant_id)
        assert row["status"] == BATCH_COMPLETED
        totals = row["totals"]
        assert totals["done"] == 50, "retried item must eventually succeed"
        assert totals["failed"] == 0
        assert totals["retried"] == 1, totals

        item = await _item_row(session, tenant_id=tenant_id, employee_number="EMP-0010")
        assert item["status"] == "done"
        assert item["retry_count"] == 1, "one transient failure must burn exactly one retry"


async def test_preflight_block_aborts_and_reenqueue_rearms(
    payroll_batch_world: dict[str, str],
) -> None:
    """Commit 2: a hard pre-flight block aborts the batch with JSONB evidence,
    and re-enqueueing after the fix re-arms the same (source, source_ref) row.

    Dedicated tenant with automation disabled and one active employee, so the
    block is ``automation_enabled``; after re-enabling, the same batch row is
    re-armed and the drained batch completes with the single employee.
    """
    tenant_id = uuid.uuid4()
    run_id = uuid.uuid4()

    async def _seed() -> None:
        async with async_session_factory() as session:
            session.add(
                TenantModel(
                    id=tenant_id,
                    name="Preflight Tenant",
                    slug=f"preflight-{tenant_id.hex[:8]}",
                    plan_tier="enterprise",
                    is_active=True,
                )
            )
            await session.flush()
            session.add(
                PayrollSettingsModel(
                    tenant_id=tenant_id,
                    default_currency="USD",
                    pf_rate=0,
                    tax_rate=0,
                    ai_automation_enabled=False,
                )
            )
            employee = EmployeeModel(
                tenant_id=tenant_id,
                id=uuid.uuid4(),
                employee_number="EMP-PF01",
                first_name="PF",
                last_name="Seed",
                job_title="Engineer",
                hire_date=date(2025, 1, 1),
            )
            session.add(employee)
            await session.flush()
            session.add(
                CompensationModel(
                    tenant_id=tenant_id,
                    employee_id=employee.id,
                    monthly_salary=5000,
                    currency="USD",
                    effective_from=date(2025, 1, 1),
                )
            )
            session.add(
                PayrollRunModel(
                    tenant_id=tenant_id,
                    id=run_id,
                    run_code="PR-PREFLIGHT",
                    period_start=date(2026, 10, 1),
                    period_end=date(2026, 10, 31),
                    status=PayrollRunStatus.DRAFT,
                )
            )
            await session.commit()

    async def _cleanup() -> None:
        async with async_session_factory() as session:
            for table in (
                "erp_payroll_entries",
                "erp_compensation",
                "erp_payroll_runs",
                "erp_payroll_settings",
                "erp_employees",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tid"),
                    {"tid": tenant_id},
                )
            await session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
            await session.commit()

    await _seed()
    try:
        async with async_session_factory() as session:
            service, payroll = _build_service(session)

            blocked = await service.enqueue(run_id=run_id, tenant_id=tenant_id)
            assert blocked.batch.status == "aborted"
            assert blocked.employee_count == 0
            assert blocked.batch.preflight is not None
            assert blocked.batch.preflight["passed"] is False
            assert "automation_enabled" in blocked.batch.preflight["blocks"]
            assert blocked.batch.preflight["roster_count"] == 1

            item_count = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM ai_payroll_batch_items WHERE batch_id = :bid"
                    ),
                    {"bid": blocked.batch.id},
                )
            ).scalar_one()
            assert item_count == 0, "a blocked batch must never create items"

            # Aborted batches are invisible to the worker (no claimable work).
            idle = await service.process_once()
            assert idle.batch_id is None, "aborted batches must not be claimable"

            # Re-enable automation and re-submit: same batch row is re-armed.
            settings = await payroll.get_settings(tenant_id)
            assert settings is not None
            await payroll.update_settings(
                dataclasses.replace(settings, ai_automation_enabled=True)
            )
            retried = await service.enqueue(run_id=run_id, tenant_id=tenant_id)
            assert retried.batch.id == blocked.batch.id, "one row per (source, source_ref)"
            assert retried.batch.status == "queued"
            assert retried.batch.preflight["passed"] is True
            assert retried.employee_count == 1

            await _drain_until_finished(service, session, batch_id=retried.batch.id)
            row = await _batch_row(session, retried.batch.id, tenant_id)
            assert row["status"] == BATCH_COMPLETED
            assert row["totals"]["done"] == 1

            # The re-armed batch carries the advisory report: this tenant's
            # employee has no bank details and no enrolled election, so the
            # failure-fix only cleared the block — the warnings survive and the
            # batch still completes.
            assert "banking" in retried.batch.preflight["warnings"]
            assert "benefit_elections" in retried.batch.preflight["warnings"]

            run_status = (
                await session.execute(
                    text("SELECT status FROM erp_payroll_runs WHERE id = :rid AND tenant_id = :tid"),
                    {"rid": run_id, "tid": tenant_id},
                )
            ).scalar_one()
            assert run_status == PayrollRunStatus.COMPUTED.value
    finally:
        await _cleanup()


async def test_enrolled_benefit_elections_seam_scopes_period() -> None:
    """The pre-flight input seam reads ONLY enrolled elections effective by the
    period end — waived rows and future-effective ones are excluded."""
    tenant_id = uuid.uuid4()
    emp_id = uuid.uuid4()

    async def _seed() -> None:
        async with async_session_factory() as session:
            session.add(
                TenantModel(
                    id=tenant_id,
                    name="Benefit Seam Tenant",
                    slug=f"benefit-seam-{tenant_id.hex[:8]}",
                    plan_tier="enterprise",
                    is_active=True,
                )
            )
            await session.flush()
            employee = EmployeeModel(
                tenant_id=tenant_id,
                id=emp_id,
                employee_number="EMP-BEN01",
                first_name="Ben",
                last_name="Fit",
                job_title="Engineer",
                hire_date=date(2024, 1, 1),
            )
            session.add(employee)
            await session.flush()
            plan = BenefitPlanModel(
                tenant_id=tenant_id,
                plan_code="MED-01",
                name="Medical",
                plan_type="medical",
                monthly_cost_cents=Decimal("150000"),
                effective_from=date(2025, 1, 1),
            )
            session.add(plan)
            await session.flush()
            session.add(
                BenefitElectionModel(
                    tenant_id=tenant_id,
                    employee_id=employee.id,
                    plan_id=plan.id,
                    status="enrolled",
                    effective_from=date(2025, 1, 1),
                )
            )
            # Enrolled but NOT yet effective by the period end — excluded.
            session.add(
                BenefitElectionModel(
                    tenant_id=tenant_id,
                    employee_id=employee.id,
                    plan_id=plan.id,
                    status="enrolled",
                    effective_from=date(2027, 1, 1),
                )
            )
            # Waived — excluded from the enrolled contract.
            session.add(
                BenefitElectionModel(
                    tenant_id=tenant_id,
                    employee_id=employee.id,
                    plan_id=plan.id,
                    status="waived",
                    effective_from=date(2025, 6, 1),
                )
            )
            await session.commit()

    async def _cleanup() -> None:
        async with async_session_factory() as session:
            for table in ("erp_benefit_elections", "erp_benefit_plans", "erp_employees"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tid"),
                    {"tid": tenant_id},
                )
            await session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
            await session.commit()

    await _seed()
    try:
        async with async_session_factory() as session:
            payroll = make_payroll_service(session)
            elections = await payroll.enrolled_benefit_elections(
                tenant_id, period_end=date(2026, 12, 31)
            )
            assert len(elections) == 1, elections
            election = elections[0]
            assert election.employee_id == emp_id
            assert election.status == "enrolled"
    finally:
        await _cleanup()


async def test_preflight_warnings_recorded_but_do_not_abort() -> None:
    """All three advisory checks (banking / benefit_elections / termination) are
    recorded in JSONB, but never abort: the batch still processes and
    completes."""
    tenant_id = uuid.uuid4()
    run_id = uuid.uuid4()

    async def _seed() -> None:
        async with async_session_factory() as session:
            session.add(
                TenantModel(
                    id=tenant_id,
                    name="Preflight Warnings Tenant",
                    slug=f"preflight-warn-{tenant_id.hex[:8]}",
                    plan_tier="enterprise",
                    is_active=True,
                )
            )
            await session.flush()
            session.add(
                PayrollSettingsModel(
                    tenant_id=tenant_id,
                    default_currency="USD",
                    pf_rate=0,
                    tax_rate=0,
                )
            )
            # Both on the roster: one missing bank details, one also carrying the
            # inconsistent active-terminated flag (future termination = flagged
            # but still payable; a past one would zero out pay_days and skip).
            for idx, (number, term_date) in enumerate(
                (("EMP-WARN01", None), ("EMP-WARN02", date(2026, 12, 15))),
                start=1,
            ):
                employee = EmployeeModel(
                    tenant_id=tenant_id,
                    employee_number=number,
                    first_name=f"Warn{idx}",
                    last_name="Seed",
                    job_title="Engineer",
                    hire_date=date(2025, 1, 1),
                    termination_date=term_date,
                )
                session.add(employee)
                await session.flush()
                session.add(
                    CompensationModel(
                        tenant_id=tenant_id,
                        employee_id=employee.id,
                        monthly_salary=5000,
                        currency="USD",
                        effective_from=date(2025, 1, 1),
                    )
                )
            session.add(
                PayrollRunModel(
                    tenant_id=tenant_id,
                    id=run_id,
                    run_code="PR-WARNINGS",
                    period_start=date(2026, 11, 1),
                    period_end=date(2026, 11, 30),
                    status=PayrollRunStatus.DRAFT,
                )
            )
            await session.commit()

    async def _cleanup() -> None:
        async with async_session_factory() as session:
            for table in (
                "erp_payroll_entries",
                "erp_compensation",
                "erp_payroll_runs",
                "erp_payroll_settings",
                "erp_employees",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tid"),
                    {"tid": tenant_id},
                )
            await session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
            await session.commit()

    await _seed()
    try:
        async with async_session_factory() as session:
            service, _payroll = _build_service(session)
            result = await service.enqueue(run_id=run_id, tenant_id=tenant_id)

            assert result.batch.status == "queued", "warnings must never abort a batch"
            assert result.employee_count == 2
            preflight = result.batch.preflight
            assert preflight is not None
            assert preflight["version"] == 2
            assert preflight["passed"] is True
            assert set(preflight["warnings"]) == {"banking", "benefit_elections", "termination"}
            assert "EMP-WARN01" in preflight["checks"]["banking"]["detail"]
            assert "EMP-WARN02" in preflight["checks"]["benefit_elections"]["detail"]
            assert "EMP-WARN02" in preflight["checks"]["termination"]["detail"]

            await _drain_until_finished(service, session, batch_id=result.batch.id)
            row = await _batch_row(session, result.batch.id, tenant_id)
            assert row["status"] == BATCH_COMPLETED
            assert row["totals"]["done"] == 2
            assert row["totals"]["failed"] == 0
    finally:
        await _cleanup()


__all__: list[str] = []


# ---------------------------------------------------------------------------
# Commit 3 — notifications (payslip-ready + admin digest) and schedules (§5.8)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def commit3_world(migrated_schema: None) -> dict[str, str]:
    """Tenant with a DRAFT run, 3 employees (2 with identity links), one
    payroll-admin role, and payroll settings — the Commit 3 integration stage."""

    async def _setup() -> dict[str, str]:
        tenant_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        batch_id = str(uuid.uuid4())
        role_id = str(uuid.uuid4())
        user_ids = {
            "user_1": str(uuid.uuid4()),
            "user_2": str(uuid.uuid4()),
            "admin": str(uuid.uuid4()),
        }
        employee_ids: dict[str, str] = {}
        async with async_session_factory() as session:
            session.add(
                TenantModel(
                    id=uuid.UUID(tenant_id),
                    name="Commit3 Tenant",
                    slug=f"commit3-{tenant_id[:8]}",
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
            for key, number, linked_user in (
                ("emp_1", "C3-0001", "user_1"),
                ("emp_2", "C3-0002", "user_2"),
                ("emp_3", "C3-0003", None),
            ):
                emp = EmployeeModel(
                    tenant_id=uuid.UUID(tenant_id),
                    id=uuid.uuid4(),
                    employee_number=number,
                    first_name=key,
                    last_name="Seed",
                    job_title="Engineer",
                    hire_date=date(2025, 1, 1),
                    user_id=(
                        uuid.UUID(user_ids[linked_user]) if linked_user is not None else None
                    ),
                    bank_account="US1234567890",
                    bank_name="Test Bank",
                )
                session.add(emp)
                await session.flush()
                employee_ids[key] = str(emp.id)
            session.add(
                PayrollRunModel(
                    tenant_id=uuid.UUID(tenant_id),
                    id=uuid.UUID(run_id),
                    run_code="PR-C3-1",
                    period_start=date(2026, 7, 1),
                    period_end=date(2026, 7, 31),
                    status=PayrollRunStatus.DRAFT,
                )
            )
            session.add(
                CoreRoleModel(
                    tenant_id=uuid.UUID(tenant_id),
                    id=uuid.UUID(role_id),
                    name="Payroll Admin",
                    permissions=["erp.payroll.ai.read", "erp.payroll.ai.run", "erp.payroll.ai.notify"],
                )
            )
            session.add(
                CoreUserRoleModel(
                    tenant_id=uuid.UUID(tenant_id),
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(user_ids["admin"]),
                    role_id=uuid.UUID(role_id),
                    scope_id=None,
                )
            )
            await session.commit()
            await engine.dispose()
        return {
            "tenant_id": tenant_id,
            "run_id": run_id,
            "batch_id": batch_id,
            "employee_ids": employee_ids,
            "user_ids": user_ids,
        }

    commit3_data = asyncio.run(_setup())

    yield commit3_data

    async def _teardown() -> None:
        tid = uuid.UUID(commit3_data["tenant_id"])
        async with async_session_factory() as session:
            for table in (
                "ai_payroll_notifications",
                "ai_payroll_notification_prefs",
                "ai_payroll_schedules",
                "ai_payroll_batch_items",
                "ai_payroll_batch_runs",
                "core_user_roles",
                "core_roles",
                "erp_payroll_entries",
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


async def _seed_terminal_batch(
    session: Any,
    *,
    world: dict[str, str],
    status: str,
    errors: dict[str, str] | None = None,
) -> uuid.UUID:
    """Create a terminal batch row with done/failed items for the world's
    employees (bypassing the compute engine — notifications only need committed
    items + a terminal batch)."""
    repo = PostgresPayrollAutomationRepository(session)
    batch = await repo.create_batch(
        tenant_id=uuid.UUID(world["tenant_id"]),
        source="payroll.run",
        source_ref=str(uuid.uuid4()),
        dry_run=False,
        totals={},
    )
    employee_ids = [uuid.UUID(eid) for eid in world["employee_ids"].values()]
    await repo.add_items(
        batch_id=batch.id,
        tenant_id=batch.tenant_id,
        employee_ids=employee_ids,
    )
    await session.flush()
    item_rows = (
        await session.execute(
            text(
                "SELECT id, employee_id FROM ai_payroll_batch_items "
                "WHERE tenant_id = :tid AND batch_id = :bid ORDER BY employee_id"
            ),
            {"tid": batch.tenant_id, "bid": batch.id},
        )
    ).all()
    for i, (item_id, _employee_id) in enumerate(item_rows):
        if status == BATCH_COMPLETED or not errors or i >= len(errors):
            await repo.mark_item_done(item_id, tenant_id=batch.tenant_id)
        else:
            await repo.mark_item_failed(
                item_id,
                tenant_id=batch.tenant_id,
                retry_count=2,
                error_text=next(iter(errors.values())),
            )
    await session.flush()
    return batch.id


class TestCommit3Notifications:
    async def test_payslip_ready_routes_by_linked_user_with_defaults_and_dedupe(
        self, commit3_world: dict[str, str]
    ) -> None:
        from core.features.payroll_automation.domain import PayrollBatchRun
        from core.features.payroll_automation.notifications import PayrollNotificationOrchestrator
        from core.features.payroll_automation.notifications_repository import (
            PostgresPayrollNotificationRepository,
        )

        async with async_session_factory() as session:
            batch_id = await _seed_terminal_batch(
                session, world=commit3_world, status=BATCH_COMPLETED
            )
            # emp_2 opts into email delivery.
            prefs = PostgresPayrollNotificationRepository(session)
            await prefs.upsert_pref(
                tenant_id=uuid.UUID(commit3_world["tenant_id"]),
                user_id=uuid.UUID(commit3_world["user_ids"]["user_2"]),
                in_app_on=True,
                email_on=True,
            )
            await session.commit()

            orch = PayrollNotificationOrchestrator(
                PostgresPayrollNotificationRepository(session),
                audit=make_core_audit_service(session),
            )
            batch = PayrollBatchRun(
                id=batch_id,
                tenant_id=uuid.UUID(commit3_world["tenant_id"]),
                source="payroll.run",
                source_ref=world_run_ref(commit3_world),
                status="processing",
                dry_run=False,
            )
            inserted = await orch.record_batch_notifications(
                tenant_id=batch.tenant_id,
                batch=batch,
                status=BATCH_COMPLETED,
                run_id=uuid.UUID(commit3_world["run_id"]),
                totals={"total": 3, "done": 3, "failed": 0, "skipped": 0},
            )
            await session.commit()

            rows = (
                await session.execute(
                    text(
                        "SELECT recipient_user_id, event_type, in_app, email_stub, dedupe_key "
                        "FROM ai_payroll_notifications WHERE tenant_id = :tid "
                        "ORDER BY recipient_user_id, dedupe_key"
                    ),
                    {"tid": batch.tenant_id},
                )
            ).all()
            by_recipient = {(row.recipient_user_id, row.event_type): row for row in rows}
            user_1 = uuid.UUID(commit3_world["user_ids"]["user_1"])
            user_2 = uuid.UUID(commit3_world["user_ids"]["user_2"])
            admin = uuid.UUID(commit3_world["user_ids"]["admin"])
            assert inserted == 3  # 2 payslip-ready (emp_3 has no user) + 1 digest

            payslip_1 = by_recipient[(user_1, "payslip_ready")]
            assert payslip_1.in_app is True and payslip_1.email_stub is False
            payslip_2 = by_recipient[(user_2, "payslip_ready")]
            assert payslip_2.in_app is True and payslip_2.email_stub is True
            digest = by_recipient[(admin, "payroll_batch_digest")]
            assert digest.event_type == "payroll_batch_digest"

            # Re-running the orchestrator inserts nothing (the dedupe criterion).
            again = await orch.record_batch_notifications(
                tenant_id=batch.tenant_id,
                batch=batch,
                status=BATCH_COMPLETED,
                run_id=uuid.UUID(commit3_world["run_id"]),
                totals={"total": 3, "done": 3, "failed": 0, "skipped": 0},
            )
            await session.commit()
            assert again == 0
            count = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM ai_payroll_notifications WHERE tenant_id = :tid"
                    ),
                    {"tid": batch.tenant_id},
                )
            ).scalar_one()
            assert count == 3

    async def test_failed_batch_digests_admin_with_failure_list(self, commit3_world: dict[str, str]) -> None:
        from core.features.payroll_automation.constants import BATCH_FAILED
        from core.features.payroll_automation.domain import PayrollBatchRun
        from core.features.payroll_automation.notifications import PayrollNotificationOrchestrator
        from core.features.payroll_automation.notifications_repository import (
            PostgresPayrollNotificationRepository,
        )

        async with async_session_factory() as session:
            batch_id = await _seed_terminal_batch(
                session, world=commit3_world, status=BATCH_FAILED,
                errors={"dummy": "tax rate missing for payroll entry"},
            )
            await session.commit()
            orch = PayrollNotificationOrchestrator(
                PostgresPayrollNotificationRepository(session),
                audit=make_core_audit_service(session),
            )
            batch = PayrollBatchRun(
                id=batch_id,
                tenant_id=uuid.UUID(commit3_world["tenant_id"]),
                source="payroll.run",
                source_ref=world_run_ref(commit3_world),
                status="processing",
                dry_run=False,
            )
            await orch.record_batch_notifications(
                tenant_id=batch.tenant_id,
                batch=batch,
                status=BATCH_FAILED,
                run_id=uuid.UUID(commit3_world["run_id"]),
                totals={"total": 3, "done": 2, "failed": 1, "skipped": 0},
            )
            await session.commit()

            rows = (
                await session.execute(
                    text(
                        "SELECT event_type, body FROM ai_payroll_notifications "
                        "WHERE tenant_id = :tid AND recipient_user_id = :admin "
                        "AND batch_id = :bid"
                    ),
                    {
                        "tid": batch.tenant_id,
                        "admin": uuid.UUID(commit3_world["user_ids"]["admin"]),
                        "bid": batch_id,
                    },
                )
            ).all()
            assert len(rows) == 1
            assert rows[0].event_type == "payroll_batch_digest"
            assert "tax rate missing for payroll entry" in rows[0].body
            # No payslip-ready rows for a failed batch (this batch, tenant-wide).
            payslip_count = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM ai_payroll_notifications "
                        "WHERE tenant_id = :tid AND event_type = 'payslip_ready' "
                        "AND batch_id = :bid"
                    ),
                    {"tid": batch.tenant_id, "bid": batch_id},
                )
            ).scalar_one()
            assert payslip_count == 0

    async def test_preference_get_and_upsert(self, commit3_world: dict[str, str]) -> None:
        from core.features.payroll_automation.notifications_repository import (
            PostgresPayrollNotificationRepository,
        )

        async with async_session_factory() as session:
            repo = PostgresPayrollNotificationRepository(session)
            user_1 = uuid.UUID(commit3_world["user_ids"]["user_1"])
            default = await repo.get_pref(uuid.UUID(commit3_world["tenant_id"]), user_1)
            assert default.in_app_on is True and default.email_on is False

            updated = await repo.upsert_pref(
                tenant_id=uuid.UUID(commit3_world["tenant_id"]),
                user_id=user_1,
                in_app_on=False,
                email_on=True,
            )
            await session.commit()
            assert updated.in_app_on is False and updated.email_on is True
            refetched = await repo.get_pref(uuid.UUID(commit3_world["tenant_id"]), user_1)
            assert refetched.in_app_on is False and refetched.email_on is True


class TestCommit3Scheduler:
    async def test_due_schedule_creates_previous_month_run_and_enqueues(
        self, commit3_world: dict[str, str]
    ) -> None:
        from datetime import UTC, datetime

        from core.features.payroll_automation.repository import PostgresPayrollAutomationRepository
        from core.features.payroll_automation.schedules import PayrollSchedulerService
        from core.features.payroll_automation.schedules_repository import (
            PostgresPayrollScheduleRepository,
        )

        async with async_session_factory() as session:
            tenant_id = uuid.UUID(commit3_world["tenant_id"])
            schedule_repo = PostgresPayrollScheduleRepository(session)
            schedule = await schedule_repo.create_schedule(
                tenant_id=tenant_id,
                name="Monthly",
                cron_expression="0 18 1 * *",
                enabled=True,
                next_run_at=datetime(2026, 8, 1, 18, 0, tzinfo=UTC),
            )
            await session.commit()

            payroll = make_payroll_service(session)
            automation = PayrollAutomationService(
                repository=PostgresPayrollAutomationRepository(session),
                payroll=payroll,
                audit=make_core_audit_service(session),
                worker_id="it-scheduler",
            )
            scheduler = PayrollSchedulerService(
                repository=schedule_repo,
                payroll=payroll,
                batches=automation,
                audit=make_core_audit_service(session),
            )
            fired = await scheduler.run_due_schedules(
                now=datetime(2026, 8, 2, 0, 0, tzinfo=UTC)
            )
            await session.commit()

            assert fired == 1
            run = (
                await session.execute(
                    text(
                        "SELECT id, period_start, period_end FROM erp_payroll_runs "
                        "WHERE tenant_id = :tid ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"tid": tenant_id},
                )
            ).one()
            assert (run.period_start, run.period_end) == (date(2026, 7, 1), date(2026, 7, 31))
            batch = (
                await session.execute(
                    text(
                        "SELECT status FROM ai_payroll_batch_runs "
                        "WHERE tenant_id = :tid AND source_ref = :run_id"
                    ),
                    {"tid": tenant_id, "run_id": str(run.id)},
                )
            ).scalar_one_or_none()
            assert batch == "queued"

            advanced = (
                await session.execute(
                    text(
                        "SELECT next_run_at FROM ai_payroll_schedules "
                        "WHERE tenant_id = :tid AND id = :sid"
                    ),
                    {"tid": tenant_id, "sid": schedule.id},
                )
            ).scalar_one()
            assert advanced is not None
            assert advanced.date() == date(2026, 9, 1)


def world_run_ref(world: dict[str, str]) -> str:
    return world["run_id"]
