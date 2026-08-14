"""PayrollService unit tests — rules 7-10, DB-free (docs/hr-payroll.md §4.8-§4.10).

Uses in-memory ``FakePayrollRepository`` and ``FakeLeaveLedger`` port doubles;
the btree_gist exclusion constraint and RLS stay in the integration suite.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from core.core.audit_events import (
    PAYROLL_COMPENSATION_RECORDED,
    PAYROLL_RUN_CREATED,
)
from core.core.audit_service import AuditService
from core.core.constants import EmploymentStatus, PayrollRounding, PayrollRunStatus
from core.core.exceptions import (
    IllegalStateTransitionError,
    PayrollEntryImmutableError,
    PayrollPeriodConflictError,
)
from core.domain import entities as ent
from core.domain.value_objects import Money
from core.features.payroll.service import PayrollService

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
EMPLOYEE = uuid.uuid4()
ACTOR = uuid.uuid4()


def _money(amount: str) -> Money:
    return Money(Decimal(amount), "USD")


def _settings() -> ent.PayrollSettings:
    return ent.PayrollSettings(
        tenant_id=TENANT,
        default_currency="USD",
        pf_rate=Decimal("0"),
        tax_rate=Decimal("0"),
        rounding=PayrollRounding.NEAREST,
        id=uuid.uuid4(),
    )


def _employee() -> ent.Employee:
    return ent.Employee(
        tenant_id=TENANT,
        employee_number="EMP-1",
        first_name="A",
        last_name="B",
        job_title="Engineer",
        hire_date=date(2020, 1, 1),
        employment_status=EmploymentStatus.ACTIVE,
        id=EMPLOYEE,
    )


class FakeAuditRepository:
    def __init__(self) -> None:
        self.added: list[ent.AuditLogEntry] = []

    async def add(self, entry: ent.AuditLogEntry) -> ent.AuditLogEntry:
        self.added.append(entry)
        return entry

    async def list(self, tenant_id: uuid.UUID, *, action: str | None = None, limit: int = 100):
        return self.added

    async def get(self, tenant_id: uuid.UUID, entry_id: uuid.UUID) -> ent.AuditLogEntry | None:
        return None


class FakeLeaveLedger:
    def __init__(
        self,
        unpaid_days: int = 0,
        *,
        accrual_types: Sequence[str] = (),
    ) -> None:
        self.unpaid_days = unpaid_days
        self.accrual_types = list(accrual_types)
        self.accrued: list[tuple[uuid.UUID, str, int]] = []

    async def approved_unpaid_days(
        self, employee_id: uuid.UUID, *, tenant_id: uuid.UUID, period_start: date, period_end: date
    ) -> int:
        return self.unpaid_days

    async def list_accrual_leave_types(self, tenant_id: uuid.UUID) -> list[str]:
        return list(self.accrual_types)

    async def accrue(
        self,
        *,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID,
        leave_type: str,
        year: int,
        actor_user_id=None,
    ) -> None:
        self.accrued.append((employee_id, leave_type, year))


class FakePayrollRepository:
    """In-memory ``PayrollRepositoryPort`` double."""

    def __init__(self) -> None:
        self.runs: dict[uuid.UUID, ent.PayrollRun] = {}
        self.entries: dict[uuid.UUID, ent.PayrollEntry] = {}
        self.compensation: list[ent.Compensation] = []
        self.settings: dict[uuid.UUID, ent.PayrollSettings] = {}
        self.run_numbers = 0
        self.employees: list[ent.Employee] = []

    async def create_compensation(self, compensation: ent.Compensation) -> ent.Compensation:
        self.compensation.append(compensation)
        return compensation

    async def get_compensation(
        self, employee_id: uuid.UUID, *, tenant_id: uuid.UUID, effective_for: date
    ) -> ent.Compensation | None:
        candidates = [
            c
            for c in self.compensation
            if c.employee_id == employee_id and c.is_active and c.effective_from <= effective_for
        ]
        return max(candidates, key=lambda c: c.effective_from) if candidates else None

    async def list_compensation(self, employee_id: uuid.UUID, *, tenant_id: uuid.UUID):
        rows = [c for c in self.compensation if c.employee_id == employee_id]
        return sorted(rows, key=lambda c: c.effective_from, reverse=True)

    async def create_run(self, run: ent.PayrollRun) -> ent.PayrollRun:
        self.runs[run.id] = run
        return run

    async def get_run(self, run_id: uuid.UUID, tenant_id: uuid.UUID) -> ent.PayrollRun | None:
        return self.runs.get(run_id)

    async def update_run(self, run: ent.PayrollRun) -> ent.PayrollRun:
        self.runs[run.id] = run
        return run

    async def list_runs(self, tenant_id: uuid.UUID, *, status=None, limit: int = 20, offset: int = 0):
        return [r for r in self.runs.values() if status is None or r.status == status]

    async def find_overlapping_run(
        self, tenant_id: uuid.UUID, *, period_start: date, period_end: date, exclude_run_id=None
    ) -> ent.PayrollRun | None:
        for run in self.runs.values():
            if run.status == PayrollRunStatus.VOID:
                continue
            if run.id == exclude_run_id:
                continue
            if run.period_start <= period_end and run.period_end >= period_start:
                return run
        return None

    async def transition_run_status(
        self,
        run_id: uuid.UUID,
        from_status: str,
        to_status: str,
        *,
        tenant_id: uuid.UUID,
        computed_by=None,
        approved_by=None,
        paid_by=None,
        computed_at=None,
        approved_at=None,
        paid_at=None,
        void_reason=None,
    ) -> ent.PayrollRun | None:
        current = self.runs.get(run_id)
        if current is None or current.status.value != from_status:
            return None
        updated = ent.PayrollRun(
            tenant_id=current.tenant_id,
            run_code=current.run_code,
            period_start=current.period_start,
            period_end=current.period_end,
            status=PayrollRunStatus(to_status),
            total_gross=current.total_gross,
            total_net=current.total_net,
            computed_by=computed_by if computed_by is not None else current.computed_by,
            approved_by=approved_by if approved_by is not None else current.approved_by,
            paid_by=paid_by if paid_by is not None else current.paid_by,
            computed_at=computed_at if computed_at is not None else current.computed_at,
            approved_at=approved_at if approved_at is not None else current.approved_at,
            paid_at=paid_at if paid_at is not None else current.paid_at,
            void_reason=void_reason if void_reason is not None else current.void_reason,
            id=current.id,
            created_at=current.created_at,
            updated_at=current.updated_at,
            skipped_employees=current.skipped_employees,
        )
        self.runs[run_id] = updated
        return updated

    async def next_run_code(self, tenant_id: uuid.UUID) -> int:
        self.run_numbers += 1
        return self.run_numbers

    async def upsert_entries(self, entries: Sequence[ent.PayrollEntry], *, tenant_id: uuid.UUID) -> None:
        for entry in entries:
            self.entries[entry.employee_id] = entry

    async def list_entries(self, run_id: uuid.UUID, *, tenant_id: uuid.UUID):
        return [e for e in self.entries.values() if e.run_id == run_id]

    async def get_entry(
        self, run_id: uuid.UUID, employee_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> ent.PayrollEntry | None:
        return self.entries.get(employee_id)

    async def get_entry_by_id(
        self, entry_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> ent.PayrollEntry | None:
        for entry in self.entries.values():
            if entry.id == entry_id:
                return entry
        return None

    async def update_entry(self, entry: ent.PayrollEntry) -> ent.PayrollEntry:
        self.entries[entry.employee_id] = entry
        return entry

    async def delete_entries_for_run(
        self, run_id: uuid.UUID, employee_ids: Sequence[uuid.UUID], *, tenant_id: uuid.UUID
    ) -> int:
        to_delete = [
            eid
            for eid, e in list(self.entries.items())
            if e.run_id == run_id and e.employee_id not in employee_ids
        ]
        for eid in to_delete:
            del self.entries[eid]
        return len(to_delete)

    async def get_settings(self, tenant_id: uuid.UUID) -> ent.PayrollSettings | None:
        return self.settings.get(tenant_id)

    async def upsert_settings(self, settings: ent.PayrollSettings) -> ent.PayrollSettings:
        self.settings[settings.tenant_id] = settings
        return settings

    async def list_active_employees(
        self, tenant_id: uuid.UUID, *, period_start: date, period_end: date
    ):
        return self.employees


def _service(
    repo: FakePayrollRepository | None = None,
    ledger: FakeLeaveLedger | None = None,
) -> tuple[PayrollService, FakePayrollRepository, FakeAuditRepository]:
    fake = repo or FakePayrollRepository()
    audit = FakeAuditRepository()
    service = PayrollService(repository=fake, leave_ledger=ledger or FakeLeaveLedger(), audit=AuditService(audit))
    return service, fake, audit


async def _create_run(service: PayrollService, *, start: date = date(2024, 5, 1)) -> ent.PayrollRun:
    return await service.create_run(
        tenant_id=TENANT,
        period_start=start,
        period_end=start + timedelta(days=29),
        actor_user_id=ACTOR,
    )


class TestRule10PeriodOverlap:
    async def test_second_run_with_overlapping_period_rejected(self) -> None:
        service, _, _ = _service()
        await _create_run(service, start=date(2024, 5, 1))
        with pytest.raises(PayrollPeriodConflictError):
            await _create_run(service, start=date(2024, 5, 15))

    async def test_non_overlapping_run_allowed(self) -> None:
        service, _, _ = _service()
        await _create_run(service, start=date(2024, 5, 1))
        second = await _create_run(service, start=date(2024, 6, 1))
        assert second.run_code == "PR-2"

    async def test_voided_run_does_not_block_new_period(self) -> None:
        service, _, _ = _service()
        first = await _create_run(service, start=date(2024, 5, 1))
        await service.void_run(run_id=first.id, tenant_id=TENANT, reason="oops")
        second = await _create_run(service, start=date(2024, 5, 10))
        assert second is not None

    async def test_run_code_is_sequential(self) -> None:
        service, _, _ = _service()
        first = await _create_run(service)
        second = await _create_run(service, start=date(2024, 6, 1))
        assert first.run_code == "PR-1"
        assert second.run_code == "PR-2"


class TestRule7CompensationPick:
    async def test_record_compensation_persists_for_the_period(self) -> None:
        """Rule 7 is repo-side (latest effective_from <= period_end, is_active).

        The service persists compensation; the fake repository emulates the
        effective-date pick so the contract is testable without a DB.
        """
        service, repo, _ = _service()
        await service.record_compensation(
            tenant_id=TENANT,
            employee_id=EMPLOYEE,
            monthly_salary=_money("2000"),
            effective_from=date(2024, 4, 1),
            actor_user_id=ACTOR,
        )
        picked = await repo.get_compensation(EMPLOYEE, tenant_id=TENANT, effective_for=date(2024, 5, 31))
        assert picked is not None and picked.monthly_salary.amount == Decimal("2000")
        assert picked.effective_from == date(2024, 4, 1)


class TestRule8Immutability:
    async def test_adjust_entry_blocked_on_approved_run(self) -> None:
        service, repo, _ = _service()
        run = await _create_run(service)
        entry = ent.PayrollEntry(
            tenant_id=TENANT,
            run_id=run.id,
            employee_id=EMPLOYEE,
            base_salary=_money("1000"),
            pay_days=30,
            gross=_money("1000"),
            deductions=_money("0"),
            net=_money("1000"),
            id=uuid.uuid4(),
        )
        repo.entries[EMPLOYEE] = entry
        repo.runs[run.id] = ent.PayrollRun(
            tenant_id=TENANT,
            run_code=run.run_code,
            period_start=run.period_start,
            period_end=run.period_end,
            status=PayrollRunStatus.APPROVED,
            id=run.id,
        )
        with pytest.raises(PayrollEntryImmutableError):
            await service.adjust_entry(
                run_id=run.id, employee_id=EMPLOYEE, tenant_id=TENANT, adjustments={"amount": "10"}
            )

    async def test_adjust_entry_blocked_on_paid_run(self) -> None:
        service, repo, _ = _service()
        run = await _create_run(service)
        entry = ent.PayrollEntry(
            tenant_id=TENANT,
            run_id=run.id,
            employee_id=EMPLOYEE,
            base_salary=_money("1000"),
            pay_days=30,
            gross=_money("1000"),
            deductions=_money("0"),
            net=_money("1000"),
            id=uuid.uuid4(),
        )
        repo.entries[EMPLOYEE] = entry
        repo.runs[run.id] = ent.PayrollRun(
            tenant_id=TENANT,
            run_code=run.run_code,
            period_start=run.period_start,
            period_end=run.period_end,
            status=PayrollRunStatus.PAID,
            id=run.id,
        )
        with pytest.raises(PayrollEntryImmutableError):
            await service.adjust_entry(
                run_id=run.id, employee_id=EMPLOYEE, tenant_id=TENANT, adjustments={"amount": "10"}
            )

    async def test_adjust_entry_merges_on_draft_run(self) -> None:
        service, repo, _ = _service()
        run = await _create_run(service)
        entry = ent.PayrollEntry(
            tenant_id=TENANT,
            run_id=run.id,
            employee_id=EMPLOYEE,
            base_salary=_money("1000"),
            pay_days=30,
            gross=_money("1000"),
            deductions=_money("0"),
            net=_money("1000"),
            adjustments={"reason": "bonus"},
            id=uuid.uuid4(),
        )
        repo.entries[EMPLOYEE] = entry
        updated = await service.adjust_entry(
            run_id=run.id, employee_id=EMPLOYEE, tenant_id=TENANT, adjustments={"amount": "100"}
        )
        assert updated.adjustments == {"reason": "bonus", "amount": "100"}


class TestRunLifecycle:
    async def test_draft_to_computed_to_approved_to_paid(self) -> None:
        service, repo, audit = _service()
        repo.settings[TENANT] = _settings()
        repo.employees = [_employee()]
        await repo.create_compensation(
            ent.Compensation(
                tenant_id=TENANT,
                employee_id=EMPLOYEE,
                monthly_salary=_money("3000"),
                effective_from=date(2024, 1, 1),
                is_active=True,
                id=uuid.uuid4(),
            )
        )
        run = await _create_run(service)
        assert run.status == PayrollRunStatus.DRAFT

        result = await service.compute_run(run_id=run.id, tenant_id=TENANT, actor_user_id=ACTOR)
        computed, entries = result.run, result.entries
        assert computed.status == PayrollRunStatus.COMPUTED
        assert len(entries) == 1
        assert computed.total_net.amount == Decimal("3000")

        approved = await service.approve_run(run_id=run.id, tenant_id=TENANT, approved_by=ACTOR)
        assert approved.status == PayrollRunStatus.APPROVED

        paid = await service.mark_paid(run_id=run.id, tenant_id=TENANT, paid_by=ACTOR)
        assert paid.status == PayrollRunStatus.PAID
        assert audit.added and audit.added[0].action == PAYROLL_RUN_CREATED

    async def test_approve_requires_computed(self) -> None:
        service, _, _ = _service()
        run = await _create_run(service)
        with pytest.raises(IllegalStateTransitionError):
            await service.approve_run(run_id=run.id, tenant_id=TENANT, approved_by=ACTOR)

    async def test_mark_paid_requires_approved(self) -> None:
        service, repo, _ = _service()
        repo.settings[TENANT] = _settings()
        run = await _create_run(service)
        await service.compute_run(run_id=run.id, tenant_id=TENANT)
        with pytest.raises(IllegalStateTransitionError):
            await service.mark_paid(run_id=run.id, tenant_id=TENANT, paid_by=ACTOR)

    async def test_void_from_computed(self) -> None:
        service, repo, _ = _service()
        repo.settings[TENANT] = _settings()
        run = await _create_run(service)
        await service.compute_run(run_id=run.id, tenant_id=TENANT)
        voided = await service.void_run(run_id=run.id, tenant_id=TENANT, reason="wrong period")
        assert voided.status == PayrollRunStatus.VOID
        assert voided.void_reason == "wrong period"

    async def test_paid_run_cannot_be_voided(self) -> None:
        service, repo, _ = _service()
        repo.settings[TENANT] = _settings()
        run = await _create_run(service)
        await service.compute_run(run_id=run.id, tenant_id=TENANT)
        await service.approve_run(run_id=run.id, tenant_id=TENANT, approved_by=ACTOR)
        await service.mark_paid(run_id=run.id, tenant_id=TENANT, paid_by=ACTOR)
        with pytest.raises(IllegalStateTransitionError):
            await service.void_run(run_id=run.id, tenant_id=TENANT)

    async def test_recompute_overwrites_entries(self) -> None:
        service, repo, _ = _service()
        repo.settings[TENANT] = _settings()
        repo.employees = [_employee()]
        await repo.create_compensation(
            ent.Compensation(
                tenant_id=TENANT,
                employee_id=EMPLOYEE,
                monthly_salary=_money("3000"),
                effective_from=date(2024, 1, 1),
                is_active=True,
                id=uuid.uuid4(),
            )
        )
        run = await _create_run(service)
        first = (await service.compute_run(run_id=run.id, tenant_id=TENANT)).entries
        second = (await service.compute_run(run_id=run.id, tenant_id=TENANT)).entries
        assert len(first) == 1 and len(second) == 1


class TestComputeUsesUnpaidLedger:
    async def test_unpaid_leave_reduces_net(self) -> None:
        service, repo, _ = _service(repo=FakePayrollRepository(), ledger=FakeLeaveLedger(unpaid_days=10))
        repo.settings[TENANT] = _settings()
        repo.employees = [_employee()]
        await repo.create_compensation(
            ent.Compensation(
                tenant_id=TENANT,
                employee_id=EMPLOYEE,
                monthly_salary=_money("3000"),
                effective_from=date(2024, 1, 1),
                is_active=True,
                id=uuid.uuid4(),
            )
        )
        run = await _create_run(service)
        result = await service.compute_run(run_id=run.id, tenant_id=TENANT)
        computed, entries = result.run, result.entries
        assert len(entries) == 1
        assert entries[0].pay_days == 20  # 30 - 10 unpaid
        assert entries[0].net.amount == Decimal("2000")
        assert computed.total_net.amount == Decimal("2000")


class TestComputeSkips:
    async def test_employee_without_compensation_is_skipped(self) -> None:
        service, repo, _ = _service()
        repo.settings[TENANT] = _settings()
        repo.employees = [_employee()]
        run = await _create_run(service)
        result = await service.compute_run(run_id=run.id, tenant_id=TENANT)
        assert result.entries == []
        assert result.skipped == [(EMPLOYEE, "no effective compensation")]
        assert result.run.status == PayrollRunStatus.COMPUTED

    async def test_employee_with_zero_payable_days_is_skipped(self) -> None:
        service, repo, _ = _service(
            ledger=FakeLeaveLedger(unpaid_days=31)  # covers the whole 30-day period
        )
        repo.settings[TENANT] = _settings()
        repo.employees = [_employee()]
        await repo.create_compensation(
            ent.Compensation(
                tenant_id=TENANT,
                employee_id=EMPLOYEE,
                monthly_salary=_money("3000"),
                effective_from=date(2024, 1, 1),
                is_active=True,
                id=uuid.uuid4(),
            )
        )
        run = await _create_run(service)
        result = await service.compute_run(run_id=run.id, tenant_id=TENANT)
        assert result.entries == []
        assert result.skipped == [(EMPLOYEE, "no payable days")]


def _employee_with_id(employee_id: uuid.UUID) -> ent.Employee:
    return ent.Employee(
        tenant_id=TENANT,
        employee_number=f"EMP-{employee_id.int % 100}",
        first_name="A",
        last_name="B",
        job_title="Engineer",
        hire_date=date(2020, 1, 1),
        employment_status=EmploymentStatus.ACTIVE,
        id=employee_id,
    )


async def _seed_compensation(repo: FakePayrollRepository, employee_id: uuid.UUID) -> None:
    await repo.create_compensation(
        ent.Compensation(
            tenant_id=TENANT,
            employee_id=employee_id,
            monthly_salary=_money("3000"),
            effective_from=date(2024, 1, 1),
            is_active=True,
            id=uuid.uuid4(),
        )
    )


class TestComputeAccrual:
    async def test_accrual_run_for_every_roster_employee_and_type(self) -> None:
        ledger = FakeLeaveLedger(accrual_types=["annual", "sick"])
        service, repo, _ = _service(ledger=ledger)
        repo.settings[TENANT] = _settings()
        repo.employees = [_employee()]
        await _seed_compensation(repo, EMPLOYEE)
        run = await _create_run(service)
        await service.compute_run(run_id=run.id, tenant_id=TENANT)
        assert ledger.accrued == [(EMPLOYEE, "annual", 2024), (EMPLOYEE, "sick", 2024)]

    async def test_no_accrual_when_no_accrual_types_configured(self) -> None:
        ledger = FakeLeaveLedger()
        service, repo, _ = _service(ledger=ledger)
        repo.settings[TENANT] = _settings()
        repo.employees = [_employee()]
        await _seed_compensation(repo, EMPLOYEE)
        run = await _create_run(service)
        await service.compute_run(run_id=run.id, tenant_id=TENANT)
        assert ledger.accrued == []


class TestComputePreservesAdjustments:
    async def test_recompute_preserves_adjustments_and_row_identity(self) -> None:
        service, repo, _ = _service()
        repo.settings[TENANT] = _settings()
        repo.employees = [_employee()]
        await _seed_compensation(repo, EMPLOYEE)
        run = await _create_run(service)
        first = (await service.compute_run(run_id=run.id, tenant_id=TENANT)).entries[0]
        await service.adjust_entry(
            run_id=run.id, employee_id=EMPLOYEE, tenant_id=TENANT, adjustments={"amount": "100"}
        )
        recomputed = (await service.compute_run(run_id=run.id, tenant_id=TENANT)).entries[0]
        assert recomputed.adjustments == {"amount": "100"}
        assert recomputed.id == first.id
        assert recomputed.net.amount == Decimal("2900")  # 3000 - 100 adjustment


class TestComputeStaleCleanup:
    async def test_recompute_drops_employees_off_the_roster(self) -> None:
        service, repo, _ = _service()
        repo.settings[TENANT] = _settings()
        other = uuid.uuid4()
        repo.employees = [_employee_with_id(EMPLOYEE), _employee_with_id(other)]
        await _seed_compensation(repo, EMPLOYEE)
        await _seed_compensation(repo, other)
        run = await _create_run(service)
        await service.compute_run(run_id=run.id, tenant_id=TENANT)
        assert len(await service.list_entries(run.id, tenant_id=TENANT)) == 2

        repo.employees = [_employee_with_id(EMPLOYEE)]  # other left the roster
        result = await service.compute_run(run_id=run.id, tenant_id=TENANT)
        entries = await service.list_entries(run.id, tenant_id=TENANT)
        assert [e.employee_id for e in entries] == [EMPLOYEE]
        assert result.entries == entries


class TestComputeSkipsPersisted:
    async def test_skipped_employees_persisted_on_run(self) -> None:
        service, repo, _ = _service()
        repo.settings[TENANT] = _settings()
        repo.employees = [_employee()]
        run = await _create_run(service)
        result = await service.compute_run(run_id=run.id, tenant_id=TENANT)
        assert result.entries == []
        assert result.run.skipped_employees == [
            {"employee_id": str(EMPLOYEE), "reason": "no effective compensation"}
        ]

    async def test_skips_survive_approval(self) -> None:
        service, repo, _ = _service()
        repo.settings[TENANT] = _settings()
        repo.employees = [_employee()]
        run = await _create_run(service)
        await service.compute_run(run_id=run.id, tenant_id=TENANT)
        approved = await service.approve_run(run_id=run.id, tenant_id=TENANT, approved_by=ACTOR)
        assert approved.skipped_employees == [
            {"employee_id": str(EMPLOYEE), "reason": "no effective compensation"}
        ]


class TestAdjustRecompute:
    async def test_adjust_entry_recomputes_net(self) -> None:
        service, repo, _ = _service()
        repo.settings[TENANT] = _settings()
        repo.employees = [_employee()]
        await _seed_compensation(repo, EMPLOYEE)
        run = await _create_run(service)
        await service.compute_run(run_id=run.id, tenant_id=TENANT)
        adjusted = await service.adjust_entry(
            run_id=run.id, employee_id=EMPLOYEE, tenant_id=TENANT, adjustments={"amount": "100"}
        )
        assert adjusted.gross.amount == Decimal("3000")
        assert adjusted.net.amount == Decimal("2900")

    async def test_adjust_entry_by_id_recomputes_net(self) -> None:
        service, repo, _ = _service()
        repo.settings[TENANT] = _settings()
        repo.employees = [_employee()]
        await _seed_compensation(repo, EMPLOYEE)
        run = await _create_run(service)
        entry = (await service.compute_run(run_id=run.id, tenant_id=TENANT)).entries[0]
        adjusted = await service.adjust_entry_by_id(
            run_id=run.id, entry_id=entry.id, tenant_id=TENANT, adjustments={"amount": "100"}
        )
        assert adjusted.gross.amount == Decimal("3000")
        assert adjusted.net.amount == Decimal("2900")


class TestRecordCompensationAudit:
    async def test_record_compensation_writes_audit_entry(self) -> None:
        service, _, audit = _service()
        await service.record_compensation(
            tenant_id=TENANT,
            employee_id=EMPLOYEE,
            monthly_salary=_money("2000"),
            effective_from=date(2024, 4, 1),
            actor_user_id=ACTOR,
        )
        assert audit.added and audit.added[-1].action == PAYROLL_COMPENSATION_RECORDED


class TestAdjustEntryById:
    async def test_merges_on_draft_run(self) -> None:
        service, repo, _ = _service()
        repo.settings[TENANT] = _settings()
        repo.employees = [_employee()]
        await repo.create_compensation(
            ent.Compensation(
                tenant_id=TENANT,
                employee_id=EMPLOYEE,
                monthly_salary=_money("3000"),
                effective_from=date(2024, 1, 1),
                is_active=True,
                id=uuid.uuid4(),
            )
        )
        run = await _create_run(service)
        entry = (await service.compute_run(run_id=run.id, tenant_id=TENANT)).entries[0]
        assert entry.id is not None

        adjusted = await service.adjust_entry_by_id(
            run_id=run.id, entry_id=entry.id, tenant_id=TENANT, adjustments={"bonus": 100}
        )
        assert adjusted.adjustments == {"bonus": 100}

        merged = await service.adjust_entry_by_id(
            run_id=run.id,
            entry_id=entry.id,
            tenant_id=TENANT,
            adjustments={"other_deduction": 50},
        )
        assert merged.adjustments == {"bonus": 100, "other_deduction": 50}

    async def test_blocked_once_run_is_approved(self) -> None:
        service, repo, _ = _service()
        repo.settings[TENANT] = _settings()
        repo.employees = [_employee()]
        await repo.create_compensation(
            ent.Compensation(
                tenant_id=TENANT,
                employee_id=EMPLOYEE,
                monthly_salary=_money("3000"),
                effective_from=date(2024, 1, 1),
                is_active=True,
                id=uuid.uuid4(),
            )
        )
        run = await _create_run(service)
        entry = (await service.compute_run(run_id=run.id, tenant_id=TENANT)).entries[0]
        await service.approve_run(run_id=run.id, tenant_id=TENANT, approved_by=ACTOR)
        assert entry.id is not None
        with pytest.raises(PayrollEntryImmutableError):
            await service.adjust_entry_by_id(
                run_id=run.id, entry_id=entry.id, tenant_id=TENANT, adjustments={"bonus": 1}
            )

    async def test_unknown_entry_raises(self) -> None:
        service, _, _ = _service()
        run = await _create_run(service)
        with pytest.raises(ValueError):
            await service.adjust_entry_by_id(
                run_id=run.id, entry_id=uuid.uuid4(), tenant_id=TENANT, adjustments={"bonus": 1}
            )


class TestCompensationHistory:
    async def test_list_compensation_newest_first(self) -> None:
        service, repo, _ = _service()
        older = ent.Compensation(
            tenant_id=TENANT,
            employee_id=EMPLOYEE,
            monthly_salary=_money("2000"),
            effective_from=date(2023, 1, 1),
            is_active=False,
            id=uuid.uuid4(),
        )
        newer = ent.Compensation(
            tenant_id=TENANT,
            employee_id=EMPLOYEE,
            monthly_salary=_money("3000"),
            effective_from=date(2024, 1, 1),
            is_active=True,
            id=uuid.uuid4(),
        )
        await repo.create_compensation(older)
        await repo.create_compensation(newer)
        history = await service.list_compensation(EMPLOYEE, tenant_id=TENANT)
        assert history == [newer, older]


class TestSettings:
    async def test_settings_upsert_and_read(self) -> None:
        service, repo, _ = _service()
        settings = _settings()
        await service.update_settings(settings, actor_user_id=ACTOR)
        fetched = await service.get_settings(TENANT)
        assert fetched is not None and fetched.tax_rate == Decimal("0")
        assert repo.settings[TENANT].tenant_id == TENANT
