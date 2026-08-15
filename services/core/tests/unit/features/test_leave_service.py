"""LeaveService unit tests — rules 1-6, DB-free (docs/hr-payroll.md §4.2-§4.7).

Uses an in-memory ``FakeHrRepository`` (a port double) — concurrency and the
DB CHECK backstop are integration-only by design.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

import pytest

from core.core.audit_events import (
    HR_LEAVE_ACCRUED,
    HR_LEAVE_APPROVED,
    HR_LEAVE_CANCELLED,
    HR_LEAVE_REQUESTED,
)
from core.core.audit_service import AuditService
from core.core.constants import EmploymentStatus, LeaveRequestStatus
from core.core.exceptions import (
    EmployeeTerminatedError,
    IllegalStateTransitionError,
    LeaveBalanceExceededError,
    SelfApprovalForbiddenError,
)
from core.domain import entities as ent
from core.features.hr.service import LeaveService

if TYPE_CHECKING:
    from collections.abc import Sequence

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()
EMPLOYEE_1 = uuid.uuid4()
EMPLOYEE_2 = uuid.uuid4()
APPROVER = uuid.uuid4()

ANNUAL = ent.LeaveType(
    tenant_id=TENANT,
    code="annual",
    name="Annual Leave",
    is_accrual=True,
    accrual_days_per_year=20,
    id=uuid.uuid4(),
)
SICK = ent.LeaveType(
    tenant_id=TENANT,
    code="sick",
    name="Sick Leave",
    is_accrual=False,
    accrual_days_per_year=None,
    id=uuid.uuid4(),
)
UNPAID = ent.LeaveType(
    tenant_id=TENANT,
    code="unpaid",
    name="Unpaid Leave",
    is_accrual=False,
    accrual_days_per_year=None,
    id=uuid.uuid4(),
)


def _employee(
    employee_id: uuid.UUID = EMPLOYEE_1,
    *,
    status: EmploymentStatus = EmploymentStatus.ACTIVE,
    hire_date: date | None = None,
) -> ent.Employee:
    return ent.Employee(
        tenant_id=TENANT,
        employee_number=f"EMP-{employee_id.int % 100}",
        first_name="A",
        last_name="B",
        job_title="Engineer",
        hire_date=hire_date or date(2020, 1, 1),
        employment_status=status,
        id=employee_id,
    )


class FakeAuditRepository:
    """Record-only audit repository (mirrors tests/unit/core/test_audit_service.py)."""

    def __init__(self) -> None:
        self.added: list[ent.AuditLogEntry] = []

    async def add(self, entry: ent.AuditLogEntry) -> ent.AuditLogEntry:
        self.added.append(entry)
        return entry

    async def list(
        self, tenant_id: uuid.UUID, *, action: str | None = None, limit: int = 100
    ) -> list[ent.AuditLogEntry]:
        return self.added

    async def get(self, tenant_id: uuid.UUID, entry_id: uuid.UUID) -> ent.AuditLogEntry | None:
        return None


class FakeHrRepository:
    """In-memory ``HrRepositoryPort`` double for leave rule tests."""

    def __init__(self, *, leave_types: Sequence[ent.LeaveType] = (ANNUAL, SICK, UNPAID)) -> None:
        self.leave_types = {lt.code: lt for lt in leave_types}
        self.employees: dict[uuid.UUID, ent.Employee] = {}
        self.requests: dict[uuid.UUID, ent.LeaveRequest] = {}
        self.movements: list[ent.LeaveMovement] = []
        self.balances: dict[tuple[uuid.UUID, str], int] = {}
        self.employee_numbers = 0

    async def create_employee(self, employee: ent.Employee) -> ent.Employee:
        self.employees[employee.id] = employee
        return employee

    async def get_employee(self, employee_id: uuid.UUID, tenant_id: uuid.UUID) -> ent.Employee | None:
        return self.employees.get(employee_id)

    async def update_employee(self, employee: ent.Employee) -> ent.Employee:
        self.employees[employee.id] = employee
        return employee

    async def list_employees(self, *args, **kwargs):
        return list(self.employees.values())

    async def next_employee_number(self, tenant_id: uuid.UUID) -> int:
        self.employee_numbers += 1
        return self.employee_numbers

    async def get_employee_by_number(self, employee_number: str, tenant_id: uuid.UUID) -> ent.Employee | None:
        for employee in self.employees.values():
            if employee.employee_number == employee_number:
                return employee
        return None

    async def create_department(self, department: ent.Department) -> ent.Department:
        return department

    async def get_department(self, department_id: uuid.UUID, tenant_id: uuid.UUID) -> ent.Department | None:
        return None

    async def update_department(self, department: ent.Department) -> ent.Department:
        return department

    async def list_departments(self, tenant_id: uuid.UUID, *, include_inactive: bool = False):
        return []

    async def get_leave_type(self, leave_type: str, tenant_id: uuid.UUID) -> ent.LeaveType | None:
        return self.leave_types.get(leave_type)

    async def list_accrual_leave_types(self, tenant_id: uuid.UUID) -> list[str]:
        return [lt.code for lt in self.leave_types.values() if lt.is_accrual]

    async def approved_unpaid_days(
        self, employee_id: uuid.UUID, *, tenant_id: uuid.UUID, period_start, period_end
    ) -> int:
        return 0

    async def add_leave_movement(self, movement: ent.LeaveMovement) -> ent.LeaveMovement:
        self.movements.append(movement)
        return movement

    async def lock_leave_balance(
        self, employee_id: uuid.UUID, leave_type: str, *, tenant_id: uuid.UUID
    ) -> None:
        """No-op in the in-memory double: nothing to serialize without a DB."""

    async def list_leave_movements(
        self, tenant_id: uuid.UUID, employee_id: uuid.UUID, leave_type: str | None = None
    ) -> list[ent.LeaveMovement]:
        return [
            m
            for m in self.movements
            if m.employee_id == employee_id and (leave_type is None or m.leave_type == leave_type)
        ]

    async def accrue_leave_movement(self, movement: ent.LeaveMovement) -> ent.LeaveMovement | None:
        for existing in self.movements:
            if (
                existing.employee_id == movement.employee_id
                and existing.leave_type == movement.leave_type
                and existing.ref_type == "annual_accrual"
                and existing.ref_id == movement.ref_id
            ):
                return None  # idempotent
        self.movements.append(movement)
        return movement

    async def recompute_balance(
        self, employee_id: uuid.UUID, leave_type: str, *, tenant_id: uuid.UUID
    ) -> int:
        # Pure read-side recompute — does NOT materialize. Only ``upsert_balance``
        # writes the materialized row (mirrors the real repository contract).
        return sum(
            m.qty for m in self.movements if m.employee_id == employee_id and m.leave_type == leave_type
        )

    async def get_balance(
        self, employee_id: uuid.UUID, leave_type: str, *, tenant_id: uuid.UUID
    ) -> ent.LeaveBalance | None:
        balance = self.balances.get((employee_id, leave_type))
        if balance is None:
            return None
        return ent.LeaveBalance(
            tenant_id=tenant_id,
            employee_id=employee_id,
            leave_type=leave_type,
            balance=balance,
            id=uuid.uuid4(),
        )

    async def upsert_balance(self, balance: ent.LeaveBalance) -> ent.LeaveBalance:
        self.balances[(balance.employee_id, balance.leave_type)] = balance.balance
        return balance

    async def create_leave_request(self, request: ent.LeaveRequest) -> ent.LeaveRequest:
        self.requests[request.id] = request
        return request

    async def get_leave_request(self, request_id: uuid.UUID, tenant_id: uuid.UUID) -> ent.LeaveRequest | None:
        return self.requests.get(request_id)

    async def update_leave_request(self, request: ent.LeaveRequest) -> ent.LeaveRequest:
        self.requests[request.id] = request
        return request

    async def transition_leave_status(
        self,
        request_id: uuid.UUID,
        from_status: str,
        to_status: str,
        *,
        tenant_id: uuid.UUID,
        approved_by: uuid.UUID | None = None,
        approved_at=None,
    ) -> ent.LeaveRequest | None:
        current = self.requests.get(request_id)
        if current is None or current.status.value != from_status:
            return None
        updated = ent.LeaveRequest(
            tenant_id=current.tenant_id,
            employee_id=current.employee_id,
            leave_type=current.leave_type,
            start_date=current.start_date,
            end_date=current.end_date,
            days=current.days,
            status=LeaveRequestStatus(to_status),
            reason=current.reason,
            approved_by=approved_by,
            approved_at=approved_at,
            id=current.id,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
        self.requests[request_id] = updated
        return updated

    async def list_leave_requests(self, tenant_id: uuid.UUID, *, status=None, employee_id=None,
                                  from_date=None, to_date=None, limit: int = 20, offset: int = 0):
        return list(self.requests.values())

    async def create_compensation(self, compensation: ent.Compensation) -> ent.Compensation:
        return compensation


def _service(
    repo: FakeHrRepository | None = None,
) -> tuple[LeaveService, FakeHrRepository, FakeAuditRepository]:
    fake = repo or FakeHrRepository()
    audit = FakeAuditRepository()
    return LeaveService(repository=fake, audit=AuditService(audit)), fake, audit


async def _request(
    service: LeaveService,
    repo: FakeHrRepository,
    *,
    leave_type: str = "annual",
    days: int = 2,
    employee_id: uuid.UUID = EMPLOYEE_1,
) -> ent.LeaveRequest:
    start = date(2024, 5, 1)
    await repo.create_employee(_employee(employee_id=employee_id))
    return await service.request(
        tenant_id=TENANT,
        employee_id=employee_id,
        leave_type=leave_type,
        start_date=start,
        end_date=date(2024, 5, 1 + days - 1),
    )


async def _accrue(service: LeaveService, repo: FakeHrRepository, *, year: int = 2024, qty: int = 10) -> None:
    await repo.add_leave_movement(
        ent.LeaveMovement(
            tenant_id=TENANT,
            employee_id=EMPLOYEE_1,
            leave_type="annual",
            qty=qty,
            ref_type="adjustment",
            ref_id=None,
            id=uuid.uuid4(),
        )
    )


class TestRule6SelfApproval:
    async def test_approver_cannot_be_requester(self) -> None:
        service, repo, _ = _service()
        req = await _request(service, repo)
        with pytest.raises(SelfApprovalForbiddenError):
            await service.approve(request_id=req.id, tenant_id=TENANT, approved_by=EMPLOYEE_1)
        assert repo.requests[req.id].status == LeaveRequestStatus.PENDING


class TestRule1ApproveWritesMovement:
    async def test_approve_writes_minus_days_and_seeds_balance(self) -> None:
        service, repo, audit = _service()
        req = await _request(service, repo, days=2)
        await _accrue(service, repo, qty=10)
        request, balance = await service.approve(request_id=req.id, tenant_id=TENANT, approved_by=APPROVER)

        assert request.status == LeaveRequestStatus.APPROVED
        assert balance == 8
        assert repo.balances[(EMPLOYEE_1, "annual")] == 8
        approval_movements = [
            m for m in repo.movements if m.ref_type == "approval" and m.ref_id == str(req.id)
        ]
        assert approval_movements and approval_movements[0].qty == -2
        assert audit.added and audit.added[-1].action == HR_LEAVE_APPROVED

    async def test_reapprove_is_a_no_op(self) -> None:
        service, repo, _ = _service()
        req = await _request(service, repo, days=2)
        await _accrue(service, repo, qty=10)
        await service.approve(request_id=req.id, tenant_id=TENANT, approved_by=APPROVER)
        movements_before = len(repo.movements)

        request, balance = await service.approve(request_id=req.id, tenant_id=TENANT, approved_by=APPROVER)

        assert request.status == LeaveRequestStatus.APPROVED
        assert balance == 8
        assert len(repo.movements) == movements_before  # no duplicate approval movement

    async def test_non_accrual_type_approval_does_not_seed_balance(self) -> None:
        service, repo, _ = _service()
        req = await _request(service, repo, leave_type="sick", days=1)
        request, _ = await service.approve(request_id=req.id, tenant_id=TENANT, approved_by=APPROVER)
        assert request.status == LeaveRequestStatus.APPROVED
        assert (EMPLOYEE_1, "sick") not in repo.balances


class TestRule2NegativeBalance:
    async def test_approval_below_zero_rejected_without_movements(self) -> None:
        service, repo, _ = _service()
        req = await _request(service, repo, days=5)  # balance is 0 (no accrual)
        with pytest.raises(LeaveBalanceExceededError):
            await service.approve(request_id=req.id, tenant_id=TENANT, approved_by=APPROVER)
        assert repo.requests[req.id].status == LeaveRequestStatus.PENDING
        assert not repo.movements  # nothing written
        assert (EMPLOYEE_1, "annual") not in repo.balances

    async def test_approval_at_exact_balance_succeeds(self) -> None:
        service, repo, _ = _service()
        req = await _request(service, repo, days=5)
        await _accrue(service, repo, qty=5)
        request, balance = await service.approve(request_id=req.id, tenant_id=TENANT, approved_by=APPROVER)
        assert request.status == LeaveRequestStatus.APPROVED
        assert balance == 0


class TestRule5Cancel:
    async def test_cancel_only_from_approved_restores_days(self) -> None:
        service, repo, audit = _service()
        req = await _request(service, repo, days=3)
        await _accrue(service, repo, qty=10)
        await service.approve(request_id=req.id, tenant_id=TENANT, approved_by=APPROVER)

        request, balance = await service.cancel(request_id=req.id, tenant_id=TENANT)

        assert request.status == LeaveRequestStatus.CANCELLED
        assert balance == 10  # days returned
        cancellation = [m for m in repo.movements if m.ref_type == "cancellation" and m.ref_id == str(req.id)]
        assert cancellation and cancellation[0].qty == 3
        assert audit.added and audit.added[-1].action == HR_LEAVE_CANCELLED

    async def test_cancel_from_pending_cancels_without_movement(self) -> None:
        service, repo, audit = _service()
        req = await _request(service, repo)
        request, balance = await service.cancel(request_id=req.id, tenant_id=TENANT)
        assert request.status == LeaveRequestStatus.CANCELLED
        assert balance == 0
        assert not [m for m in repo.movements if m.ref_id == str(req.id)]
        assert audit.added and audit.added[-1].action == HR_LEAVE_CANCELLED

    async def test_cancel_from_rejected_still_blocked(self) -> None:
        service, repo, _ = _service()
        req = await _request(service, repo)
        await service.reject(request_id=req.id, tenant_id=TENANT)
        with pytest.raises(IllegalStateTransitionError):
            await service.cancel(request_id=req.id, tenant_id=TENANT)


class TestRule4Accrual:
    async def test_accrual_is_idempotent_per_employee_type_year(self) -> None:
        service, repo, audit = _service()
        await repo.create_employee(_employee())

        first = await service.accrue(tenant_id=TENANT, employee_id=EMPLOYEE_1, leave_type="annual", year=2024)
        second = await service.accrue(tenant_id=TENANT, employee_id=EMPLOYEE_1, leave_type="annual", year=2024)

        assert first is not None and second is None
        annual = [m for m in repo.movements if m.ref_type == "annual_accrual" and m.ref_id == "2024"]
        assert len(annual) == 1
        assert audit.added and audit.added[-1].action == HR_LEAVE_ACCRUED

    async def test_non_accrual_type_cannot_accrue(self) -> None:
        service, _, _ = _service()
        with pytest.raises(ValueError, match="does not accrue"):
            await service.accrue(tenant_id=TENANT, employee_id=EMPLOYEE_1, leave_type="sick", year=2024)

    async def test_full_year_accrual_uses_leave_type_days(self) -> None:
        service, repo, _ = _service()
        employee = _employee(hire_date=date(2024, 1, 1))
        await repo.create_employee(employee)
        movement = await service.accrue(tenant_id=TENANT, employee_id=EMPLOYEE_1, leave_type="annual", year=2024)
        assert movement is not None
        assert movement.qty == 20  # hired Jan 1 → full year

    async def test_prorated_accrual_from_hire_date(self) -> None:
        service, repo, _ = _service()
        await repo.create_employee(_employee(hire_date=date(2024, 7, 1)))
        movement = await service.accrue(tenant_id=TENANT, employee_id=EMPLOYEE_1, leave_type="annual", year=2024)
        assert movement is not None
        remaining = 365 - (date(2024, 7, 1).timetuple().tm_yday - 1)  # 184 days left
        expected = int((Decimal("20") * Decimal(remaining) / Decimal(365)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        assert movement.qty == expected
        assert movement.qty == 10  # half-year → 10 days


class TestRule3AtomicApproval:
    async def test_guard_transition_wins_when_status_changed(self) -> None:
        service, repo, _ = _service()
        req = await _request(service, repo, days=2)
        await _accrue(service, repo, qty=10)
        repo.requests[req.id] = ent.LeaveRequest(
            tenant_id=req.tenant_id,
            employee_id=req.employee_id,
            leave_type=req.leave_type,
            start_date=req.start_date,
            end_date=req.end_date,
            days=req.days,
            status=LeaveRequestStatus.APPROVED,  # concurrent approve already flipped it
            reason=req.reason,
            id=req.id,
        )
        # Guard returns None → service re-reads and treats as already-approved.
        request, balance = await service.approve(request_id=req.id, tenant_id=TENANT, approved_by=APPROVER)
        assert request.status == LeaveRequestStatus.APPROVED
        assert balance == 10


class TestRequest:
    async def test_request_computes_days_server_side(self) -> None:
        service, repo, audit = _service()
        req = await _request(service, repo, days=4)
        assert req.days == 4
        assert req.status == LeaveRequestStatus.PENDING
        assert audit.added and audit.added[-1].action == HR_LEAVE_REQUESTED

    async def test_unknown_leave_type_rejected(self) -> None:
        service, repo, _ = _service()
        with pytest.raises(ValueError, match="unknown leave type"):
            await _request(service, repo, leave_type="bogus")

    async def test_request_rejected_for_terminated_employee(self) -> None:
        service, repo, _ = _service()
        await repo.create_employee(_employee(status=EmploymentStatus.TERMINATED))
        with pytest.raises(EmployeeTerminatedError):
            await service.request(
                tenant_id=TENANT,
                employee_id=EMPLOYEE_1,
                leave_type="annual",
                start_date=date(2024, 5, 1),
                end_date=date(2024, 5, 2),
            )
        assert not repo.requests


class TestTerminatedEmployeeGuards:
    async def test_approve_rejected_for_terminated_employee(self) -> None:
        service, repo, _ = _service()
        req = await _request(service, repo)
        repo.employees[EMPLOYEE_1] = _employee(status=EmploymentStatus.TERMINATED)
        with pytest.raises(EmployeeTerminatedError):
            await service.approve(request_id=req.id, tenant_id=TENANT, approved_by=APPROVER)
        assert repo.requests[req.id].status == LeaveRequestStatus.PENDING


class TestLeaveLedgerDelegates:
    async def test_list_accrual_leave_types_returns_only_accrual_types(self) -> None:
        service, _, _ = _service()
        assert await service.list_accrual_leave_types(TENANT) == ["annual"]

    async def test_approved_unpaid_days_delegates_to_repository(self) -> None:
        service, _, _ = _service()
        assert (
            await service.approved_unpaid_days(
                EMPLOYEE_1,
                tenant_id=TENANT,
                period_start=date(2024, 5, 1),
                period_end=date(2024, 5, 31),
            )
            == 0
        )


__all__ = ["FakeAuditRepository", "FakeHrRepository"]
