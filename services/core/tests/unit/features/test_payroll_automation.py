"""PayrollAutomationService unit tests — batch engine logic, DB-free.

Doubles implement the two ports (:class:`PayrollAutomationRepositoryPort` and
the compute seam) in memory, so these tests pin the engine's own invariants:
enqueue guards + idempotency, pre-flight blocking (settings/automation/period/
roster/run checks abort the batch with JSONB evidence), the transient/retry
budget state machine, the ``PermanentBatchItemError`` terminal path, dry-run,
and run finalization.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from core.core.constants import EmploymentStatus
from core.domain.value_objects import Money
from core.features.payroll.models.payroll_run import PayrollRunStatus
from core.features.payroll_automation.constants import SOURCE_PAYROLL_RUN
from core.features.payroll_automation.domain import PayrollBatchItem, PayrollBatchRun
from core.features.payroll_automation.service import (
    PayrollAutomationService,
    PermanentBatchItemError,
)

pytestmark = pytest.mark.unit

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
RUN_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
EMP_IDS = [
    uuid.UUID("33333333-3333-3333-3333-333333333333"),
    uuid.UUID("44444444-4444-4444-4444-444444444444"),
]


def _uid() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


@dataclass
class _Run:
    id: uuid.UUID
    status: PayrollRunStatus = PayrollRunStatus.DRAFT
    run_code: str = "PR-0001"
    period_start: date = date(2026, 7, 1)
    period_end: date = date(2026, 7, 31)


@dataclass
class _Settings:
    ai_automation_enabled: bool = True


@dataclass
class _Emp:
    id: uuid.UUID
    employee_number: str = ""
    bank_account: str | None = None
    bank_name: str | None = None
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE
    termination_date: date | None = None


@dataclass
class _Election:
    employee_id: uuid.UUID
    status: str = "enrolled"


@dataclass
class _Entry:
    gross: Money
    net: Money


class FakePayroll:
    """Stand-in for PayrollService's compute seam."""

    def __init__(self) -> None:
        self.runs: dict[uuid.UUID, _Run] = {RUN_ID: _Run(RUN_ID)}
        self.roster: list[_Emp] = [
            _Emp(EMP_IDS[0], "EMP-0001", "US1234567890", "Bank"),
            _Emp(EMP_IDS[1], "EMP-0002", "US0987654321", "Bank"),
        ]
        self.elections: list[_Election] = [_Election(EMP_IDS[0]), _Election(EMP_IDS[1])]
        self.failures: dict[uuid.UUID, list[Exception]] = {}
        self.skip_employee: uuid.UUID | None = None
        self.finalized: list[dict[str, object]] = []
        self.settings: _Settings | None = _Settings()
        self.overlapping: _Run | None = None

    async def get_run(self, run_id: uuid.UUID, *, tenant_id: uuid.UUID) -> _Run | None:
        return self.runs.get(run_id)

    async def is_computable(self, run: _Run) -> bool:
        return run.status in (PayrollRunStatus.DRAFT, PayrollRunStatus.COMPUTED)

    async def get_settings(self, tenant_id: uuid.UUID) -> _Settings | None:
        return self.settings

    async def find_overlapping_run(
        self, tenant_id: uuid.UUID, *, period_start, period_end
    ) -> _Run | None:
        return self.overlapping

    async def active_employees(self, run_id: uuid.UUID, *, tenant_id: uuid.UUID) -> list[_Emp]:
        return list(self.roster)

    async def enrolled_benefit_elections(
        self, tenant_id: uuid.UUID, *, period_end
    ) -> list[_Election]:
        return list(self.elections)

    async def compute_single(
        self,
        *,
        run_id: uuid.UUID,
        employee_id: uuid.UUID,
        tenant_id: uuid.UUID,
        persist: bool = True,
    ) -> tuple[_Entry | None, str | None]:
        pending = self.failures.get(employee_id)
        if pending:
            raise pending.pop(0)
        if employee_id == self.skip_employee:
            return None, "no effective compensation for this period"
        return (
            _Entry(Money(Decimal("5000.00"), "USD"), Money(Decimal("4500.00"), "USD")),
            None,
        )

    async def finalize_compute(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None = None,
        skipped: list[dict[str, str]] | None = None,
    ) -> _Run:
        self.finalized.append({"run_id": run_id, "skipped": skipped or []})
        self.runs[run_id].status = PayrollRunStatus.COMPUTED
        return self.runs[run_id]


class FakeRepo:
    """In-memory :class:`PayrollAutomationRepositoryPort`."""

    def __init__(self) -> None:
        self.batches: list[dict[str, object]] = []
        self.items: list[dict[str, object]] = []

    async def get_batch(self, *, tenant_id, source, source_ref):
        batches = self._batches(tenant_id, source, source_ref)
        return batches[0] if batches else None

    def _batches(self, tenant_id, source, source_ref) -> list[PayrollBatchRun]:
        return [
            self._to_run(b)
            for b in self.batches
            if b["tenant_id"] == tenant_id
            and b["source"] == source
            and b["source_ref"] == source_ref
        ]

    def _to_run(self, b: dict[str, object]) -> PayrollBatchRun:
        return PayrollBatchRun(
            id=b["id"],
            tenant_id=b["tenant_id"],
            source=b["source"],
            source_ref=b["source_ref"],
            status=b["status"],
            dry_run=b["dry_run"],
            claimed_by=b["claimed_by"],
            preflight=b.get("preflight"),
            totals=b["totals"],
            started_at=b["started_at"],
            finished_at=b["finished_at"],
        )

    async def get_batch_by_id(self, batch_id, *, tenant_id):
        for b in self.batches:
            if b["id"] == batch_id and b["tenant_id"] == tenant_id:
                return self._to_run(b)
        return None

    async def create_batch(self, *, tenant_id, source, source_ref, dry_run, totals, preflight=None):
        batch = {
            "id": _uid(),
            "tenant_id": tenant_id,
            "source": source,
            "source_ref": source_ref,
            "status": "queued",
            "dry_run": dry_run,
            "claimed_by": None,
            "preflight": preflight,
            "totals": dict(totals),
            "started_at": None,
            "finished_at": None,
        }
        self.batches.append(batch)
        return self._to_run(batch)

    async def add_items(self, *, batch_id, tenant_id, employee_ids):
        for eid in employee_ids:
            self.items.append(
                {
                    "id": _uid(),
                    "tenant_id": tenant_id,
                    "batch_id": batch_id,
                    "employee_id": eid,
                    "status": "pending",
                    "retry_count": 0,
                    "error_text": None,
                }
            )

    async def claim_next_batch(self, worker_id: str) -> PayrollBatchRun | None:
        for b in self.batches:
            if b["status"] == "queued" or (
                b["status"] == "processing" and b["claimed_by"] == worker_id
            ):
                b["status"] = "processing"
                b["claimed_by"] = worker_id
                b["started_at"] = datetime.now(UTC)
                return self._to_run(b)
        return None

    async def finalize_batch(self, *, batch_id, tenant_id, status, totals, finished_at):
        for b in self.batches:
            if b["id"] == batch_id:
                b["status"] = status
                b["totals"] = dict(totals)
                b["finished_at"] = finished_at

    async def abort_batch(self, *, batch_id, tenant_id, totals, finished_at):
        for b in self.batches:
            if b["id"] == batch_id and b["tenant_id"] == tenant_id:
                b["status"] = "aborted"
                b["totals"] = dict(totals)
                b["finished_at"] = finished_at
                return self._to_run(b)
        raise ValueError(f"batch {batch_id} is not abortable")

    async def reset_batch(self, *, batch_id, tenant_id, dry_run, totals, preflight):
        for b in self.batches:
            if b["id"] == batch_id and b["tenant_id"] == tenant_id and b["status"] == "aborted":
                b["status"] = "queued"
                b["claimed_by"] = None
                b["started_at"] = None
                b["finished_at"] = None
                b["dry_run"] = dry_run
                b["totals"] = dict(totals)
                b["preflight"] = preflight
                return self._to_run(b)
        raise ValueError(f"batch {batch_id} is not aborted and cannot be reset")

    async def claim_next_item(self, *, batch_id, tenant_id, max_retries):
        for item in self.items:
            if item["batch_id"] != batch_id:
                continue
            if item["status"] == "pending" or (
                item["status"] == "failed" and item["retry_count"] < max_retries
            ):
                return self._to_item(item)
        return None

    def _to_item(self, item: dict[str, object]) -> PayrollBatchItem:
        return PayrollBatchItem(
            id=item["id"],
            tenant_id=item["tenant_id"],
            batch_id=item["batch_id"],
            employee_id=item["employee_id"],
            status=item["status"],
            retry_count=item["retry_count"],
            error_text=item["error_text"],
        )

    async def mark_item_done(self, item_id, *, tenant_id):
        for item in self.items:
            if item["id"] == item_id:
                item["status"] = "done"

    async def mark_item_failed(self, item_id, *, tenant_id, retry_count, error_text):
        for item in self.items:
            if item["id"] == item_id:
                item["status"] = "failed"
                item["retry_count"] = retry_count
                item["error_text"] = error_text

    async def claimable_item_count(self, *, batch_id, tenant_id, max_retries):
        return sum(
            1
            for item in self.items
            if item["batch_id"] == batch_id
            and (
                item["status"] == "pending"
                or (item["status"] == "failed" and item["retry_count"] < max_retries)
            )
        )

    async def update_totals(self, *, batch_id, tenant_id, totals):
        for b in self.batches:
            if b["id"] == batch_id:
                b["totals"] = dict(totals)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _make_engine(
    *, max_retries: int = 2, items_per_tick: int = 10
) -> tuple[PayrollAutomationService, FakeRepo, FakePayroll]:
    repo = FakeRepo()
    payroll = FakePayroll()
    service = PayrollAutomationService(
        repository=repo,
        payroll=payroll,
        audit=None,  # the engine does not emit events itself
        worker_id="unit-worker",
        max_retries=max_retries,
        items_per_tick=items_per_tick,
    )
    return service, repo, payroll


async def _enqueue(service: PayrollAutomationService, *, dry_run: bool = False):
    return await service.enqueue(run_id=RUN_ID, tenant_id=TENANT_ID, dry_run=dry_run)


class TestEnqueue:
    async def test_creates_one_item_per_roster_employee(self):
        service, repo, _payroll = _make_engine()
        result = await _enqueue(service)
        assert result.employee_count == 2
        assert result.batch.source == SOURCE_PAYROLL_RUN
        assert result.batch.source_ref == str(RUN_ID)
        assert result.batch.status == "queued"
        assert result.batch.totals["total"] == 2
        assert result.batch.preflight is not None
        assert result.batch.preflight["passed"] is True
        assert len([i for i in repo.items if i["batch_id"] == result.batch.id]) == 2

    async def test_enqueue_is_idempotent_per_run(self):
        service, repo, _payroll = _make_engine()
        first = await _enqueue(service)
        again = await _enqueue(service)
        assert again.batch.id == first.batch.id
        assert again.employee_count == first.employee_count
        assert len(repo.batches) == 1
        assert len([i for i in repo.items if i["batch_id"] == first.batch.id]) == 2

    async def test_missing_run_is_rejected(self):
        service, _repo, payroll = _make_engine()
        payroll.runs.pop(RUN_ID)
        with pytest.raises(ValueError, match="not found"):
            await _enqueue(service)

    async def test_non_computable_run_is_aborted_with_preflight_evidence(self):
        service, repo, payroll = _make_engine()
        payroll.runs[RUN_ID].status = PayrollRunStatus.APPROVED
        result = await _enqueue(service)
        assert result.batch.status == "aborted"
        assert result.employee_count == 0
        assert result.batch.totals["total"] == 0
        preflight = result.batch.preflight
        assert preflight["passed"] is False
        assert "run" in preflight["blocks"]
        assert len([i for i in repo.items if i["batch_id"] == result.batch.id]) == 0

    async def test_missing_settings_is_aborted(self):
        service, _repo, payroll = _make_engine()
        payroll.settings = None
        result = await _enqueue(service)
        assert result.batch.status == "aborted"
        assert "settings" in result.batch.preflight["blocks"]

    async def test_automation_disabled_is_aborted(self):
        service, repo, payroll = _make_engine()
        payroll.settings = _Settings(ai_automation_enabled=False)
        result = await _enqueue(service)
        assert result.batch.status == "aborted"
        assert result.batch.preflight["passed"] is False
        assert "automation_enabled" in result.batch.preflight["blocks"]
        assert len([i for i in repo.items if i["batch_id"] == result.batch.id]) == 0

    async def test_period_conflict_is_aborted(self):
        service, repo, payroll = _make_engine()
        payroll.overlapping = _Run(_uid(), run_code="PR-WINNER")
        result = await _enqueue(service)
        assert result.batch.status == "aborted"
        assert "period" in result.batch.preflight["blocks"]
        assert "PR-WINNER" in result.batch.preflight["checks"]["period"]["detail"]
        assert len([i for i in repo.items if i["batch_id"] == result.batch.id]) == 0

    async def test_empty_roster_is_aborted(self):
        service, _repo, payroll = _make_engine()
        payroll.roster = []
        result = await _enqueue(service)
        assert result.batch.status == "aborted"
        assert "roster" in result.batch.preflight["blocks"]
        assert result.batch.preflight["roster_count"] == 0

    async def test_blocked_dry_run_aborts_too(self):
        service, _repo, payroll = _make_engine()
        payroll.settings = _Settings(ai_automation_enabled=False)
        result = await _enqueue(service, dry_run=True)
        assert result.batch.status == "aborted"
        assert result.batch.dry_run is True

    async def test_reenqueue_after_abort_rearms_same_batch_row(self):
        service, repo, payroll = _make_engine()
        payroll.settings = _Settings(ai_automation_enabled=False)
        blocked = await _enqueue(service)
        assert blocked.batch.status == "aborted"

        payroll.settings = _Settings(ai_automation_enabled=True)
        retried = await _enqueue(service)
        assert retried.batch.id == blocked.batch.id, "one row per (source, source_ref)"
        assert retried.batch.status == "queued"
        assert retried.batch.preflight["passed"] is True
        assert retried.employee_count == 2
        assert len(repo.batches) == 1
        assert len([i for i in repo.items if i["batch_id"] == retried.batch.id]) == 2


class TestPreflightWarnings:
    """Advisory checks never abort a batch — they warn and still process."""

    async def _enqueue(self, service, **kwargs):
        return await service.enqueue(run_id=RUN_ID, tenant_id=TENANT_ID, **kwargs)

    async def test_clean_roster_reports_zero_warnings(self):
        service, _repo, _payroll = _make_engine()
        result = await self._enqueue(service)
        assert result.batch.status == "queued"
        assert result.batch.preflight["version"] == 2
        assert result.batch.preflight["passed"] is True
        assert result.batch.preflight["warnings"] == []
        assert result.batch.preflight["blocks"] == []
        for key in ("banking", "benefit_elections", "termination"):
            assert result.batch.preflight["checks"][key]["status"] == "ok"

    async def test_missing_bank_details_warns_but_does_not_block(self):
        service, repo, payroll = _make_engine()
        payroll.roster[0].bank_account = None
        payroll.roster[0].bank_name = None
        result = await self._enqueue(service)
        assert result.batch.status == "queued"
        assert result.batch.preflight["passed"] is True
        assert "banking" in result.batch.preflight["warnings"]
        assert "EMP-0001" in result.batch.preflight["checks"]["banking"]["detail"]
        assert result.employee_count == 2, "warnings must not drop items"
        assert len([i for i in repo.items if i["batch_id"] == result.batch.id]) == 2

    async def test_employee_without_enrolled_election_warns(self):
        service, _repo, payroll = _make_engine()
        payroll.elections = [_Election(EMP_IDS[0])]
        result = await self._enqueue(service)
        assert result.batch.preflight["passed"] is True
        assert "benefit_elections" in result.batch.preflight["warnings"]
        assert "EMP-0002" in result.batch.preflight["checks"]["benefit_elections"]["detail"]

    async def test_active_employee_flagged_with_termination_date_warns(self):
        service, _repo, payroll = _make_engine()
        payroll.roster[0].termination_date = date(2026, 7, 20)
        result = await self._enqueue(service)
        assert result.batch.preflight["passed"] is True
        assert "termination" in result.batch.preflight["warnings"]
        assert "EMP-0001" in result.batch.preflight["checks"]["termination"]["detail"]

    async def test_terminated_during_period_is_not_warned(self):
        service, _repo, payroll = _make_engine()
        payroll.roster[0].employment_status = EmploymentStatus.TERMINATED
        payroll.roster[0].termination_date = date(2026, 7, 20)
        result = await self._enqueue(service)
        assert result.batch.preflight["passed"] is True
        assert "termination" not in result.batch.preflight["warnings"]

    async def test_warnings_do_not_abort_blocked_flow(self):
        # A hard block still aborts, but the warnings report is still attached.
        service, _repo, payroll = _make_engine()
        payroll.settings = _Settings(ai_automation_enabled=False)
        payroll.roster[0].bank_account = None
        result = await self._enqueue(service)
        assert result.batch.status == "aborted"
        assert "automation_enabled" in result.batch.preflight["blocks"]
        assert "banking" in result.batch.preflight["warnings"]


class TestProcessOnce:
    async def test_no_work_returns_empty_tick(self):
        service, _repo, _payroll = _make_engine()
        result = await service.process_once()
        assert result.batch_id is None
        assert result.items_processed == 0
        assert result.status_changed is False

    async def test_happy_path_finalizes_batch_and_run(self):
        service, repo, payroll = _make_engine()
        await _enqueue(service)
        tick = await service.process_once()
        assert tick.items_processed == 2
        assert tick.status_changed is True
        batch = next(iter(repo.batches))
        assert batch["status"] == "completed"
        totals = batch["totals"]
        assert totals["done"] == 2
        assert totals["failed"] == 0
        assert totals["skipped"] == 0
        assert totals["gross"] == "10000.00"  # 2 x 5000
        assert totals["net"] == "9000.00"  # 2 x 4500
        assert len(payroll.finalized) == 1
        assert payroll.finalized[0]["skipped"] == []
        assert all(i["status"] == "done" for i in repo.items)

    async def test_skipped_employee_records_projection_but_counts_as_done(self):
        service, repo, payroll = _make_engine()
        payroll.skip_employee = EMP_IDS[0]
        await _enqueue(service)
        await service.process_once()
        batch = next(iter(repo.batches))
        assert batch["totals"]["skipped"] == 1
        assert batch["totals"]["done"] == 1
        assert batch["totals"]["failed"] == 0
        assert payroll.finalized[0]["skipped"] != []

    async def test_dry_run_never_finalizes_run(self):
        service, _repo, payroll = _make_engine()
        await _enqueue(service, dry_run=True)
        tick = await service.process_once()
        assert tick.status_changed is True
        assert payroll.finalized == [], "dry-run must not touch the payroll run"
        assert payroll.runs[RUN_ID].status == PayrollRunStatus.DRAFT

    async def test_transient_failure_burns_one_retry_then_succeeds(self):
        service, repo, payroll = _make_engine()
        payroll.failures[EMP_IDS[0]] = [RuntimeError("hiccup")]
        await _enqueue(service)

        first = await service.process_once()
        assert first.status_changed is False  # retry deferred to a later tick
        assert first.items_processed == 1  # EMP-0001 failed; tick yields
        item = next(i for i in repo.items if i["employee_id"] == EMP_IDS[0])
        assert item["status"] == "failed"
        assert item["retry_count"] == 1
        assert "hiccup" in item["error_text"]

        second = await service.process_once()  # a LATER tick re-claims the item
        assert second.status_changed is True
        batch = next(iter(repo.batches))
        assert batch["totals"]["done"] == 2
        assert batch["totals"]["retried"] == 1
        assert batch["totals"]["failed"] == 0
        assert next(i for i in repo.items if i["employee_id"] == EMP_IDS[0])["status"] == "done"

    async def test_transient_failures_exhaust_budget_to_terminal_failed(self):
        service, repo, payroll = _make_engine()
        payroll.failures[EMP_IDS[0]] = [RuntimeError("a"), RuntimeError("b")]
        await _enqueue(service)

        first = await service.process_once()
        assert first.status_changed is False
        second = await service.process_once()
        assert second.status_changed is True  # budget hit on the 2nd re-claim

        batch = next(iter(repo.batches))
        assert batch["totals"]["done"] == 1
        assert batch["totals"]["retried"] == 1
        assert batch["totals"]["failed"] == 1
        item = next(i for i in repo.items if i["employee_id"] == EMP_IDS[0])
        assert item["status"] == "failed"
        assert item["retry_count"] == 2

    async def test_permanent_failure_is_terminal_and_never_reclaimed(self):
        service, repo, payroll = _make_engine()
        payroll.failures[EMP_IDS[0]] = [PermanentBatchItemError("injected permanent")]
        await _enqueue(service)

        tick = await service.process_once()
        assert tick.status_changed is True, "permanent failure must not keep the batch open"
        batch = next(iter(repo.batches))
        assert batch["totals"]["done"] == 1
        assert batch["totals"]["failed"] == 1
        assert batch["totals"]["retried"] == 0
        item = next(i for i in repo.items if i["employee_id"] == EMP_IDS[0])
        assert item["status"] == "failed"
        assert item["retry_count"] == 2, "permanent failure must burn no retries"
        assert "injected permanent" in item["error_text"]

    async def test_partial_tick_resumes_later(self):
        service, repo, _payroll = _make_engine(items_per_tick=1)
        await _enqueue(service)
        first = await service.process_once()
        second = await service.process_once()
        assert first.items_processed == 1 and first.status_changed is False
        assert second.items_processed == 1 and second.status_changed is True
        assert all(i["status"] == "done" for i in repo.items)


class TestBatchStatus:
    async def test_projections(self):
        service, _repo, _payroll = _make_engine()
        result = await _enqueue(service)
        projection = await service.batch_status(result.batch.id, tenant_id=TENANT_ID)
        assert projection["status"] == "queued"
        assert projection["dry_run"] is False
        assert projection["totals"]["total"] == 2
        assert projection["claimed_by"] is None
        assert projection["preflight"] is not None
        assert projection["preflight"]["passed"] is True
        with pytest.raises(ValueError, match="not found"):
            await service.batch_status(_uid(), tenant_id=TENANT_ID)


__all__: list[str] = []
