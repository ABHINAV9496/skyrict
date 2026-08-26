"""HR repository and integration ports — persistence + cross-feature contracts.

Declares what the repository must offer so services depend on this Protocol
(hexagonal "port") rather than the concrete SQLAlchemy implementation. Also
holds the cross-feature ``IdentityUserPort`` (validation against the identity
service, per docs/modules/hr-payroll.md §6 Step 2). The ``LeaveLedgerPort``
that payroll consumes is declared in ``features/payroll/ports.py`` and is
implemented by the (deferred) HR repository.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Protocol

from core.domain import entities as ent


class IdentityUserPort(Protocol):
    """Identity integration — validates that a user exists in the routed tenant.

    Deliberately validate-only: this port never creates users. The concrete
    implementation calls the identity service (in-process or HTTP) and is wired
    at the composition root (``api/deps.py``).
    """

    async def validate_user(self, user_id: uuid.UUID, *, tenant_id: uuid.UUID) -> None:
        """Raise ``skyrict_common.NotFoundError`` if the user is unknown/inactive."""
        ...


class HrRepositoryPort(Protocol):
    """Persistence contract for departments, employees, leave ledger & balances."""

    # --- Departments ---
    async def create_department(self, department: ent.Department) -> ent.Department: ...

    async def get_department(
        self, department_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ent.Department | None: ...

    async def update_department(self, department: ent.Department) -> ent.Department: ...

    async def list_departments(
        self, tenant_id: uuid.UUID, *, include_inactive: bool = False
    ) -> Sequence[ent.Department]: ...

    # --- Employees ---
    async def create_employee(self, employee: ent.Employee) -> ent.Employee: ...

    async def get_employee(
        self, employee_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ent.Employee | None: ...

    async def update_employee(self, employee: ent.Employee) -> ent.Employee: ...

    async def list_employees(
        self,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        department_id: uuid.UUID | None = None,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[ent.Employee]: ...

    async def next_employee_number(self, tenant_id: uuid.UUID) -> int: ...

    async def get_employee_by_number(
        self, employee_number: str, tenant_id: uuid.UUID
    ) -> ent.Employee | None: ...

    async def get_employee_by_user_id(
        self, user_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ent.Employee | None: ...

    # --- Leave types ---
    async def get_leave_type(
        self, leave_type: str, tenant_id: uuid.UUID
    ) -> ent.LeaveType | None: ...

    async def list_leave_types(self, tenant_id: uuid.UUID) -> Sequence[ent.LeaveType]: ...

    async def list_accrual_leave_types(self, tenant_id: uuid.UUID) -> Sequence[str]:
        """Return leave-type names that accrue annually (``accrues`` = true)."""
        ...

    # --- Leave policy ---
    async def get_leave_policy(self, tenant_id: uuid.UUID) -> ent.LeavePolicy | None: ...

    async def upsert_leave_policy(self, policy: ent.LeavePolicy) -> ent.LeavePolicy: ...

    # --- Leave ledger & balances ---
    async def add_leave_movement(self, movement: ent.LeaveMovement) -> ent.LeaveMovement: ...

    async def list_leave_movements(
        self,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID,
        leave_type: str | None = None,
    ) -> Sequence[ent.LeaveMovement]: ...

    async def accrue_leave_movement(
        self, movement: ent.LeaveMovement
    ) -> ent.LeaveMovement | None: ...

    async def lock_leave_balance(
        self, employee_id: uuid.UUID, leave_type: str, *, tenant_id: uuid.UUID
    ) -> None:
        """Serialize concurrent balance mutations for one employee/leave_type.

        Guarantees the ``erp_leave_balances`` lock row exists (seeds it) and
        takes ``SELECT ... FOR UPDATE`` on it (docs §4.3). MUST be called
        before any read-then-write of that balance, inside the same
        transaction; the lock is held until commit/rollback.
        """
        ...

    async def recompute_balance(
        self, employee_id: uuid.UUID, leave_type: str, *, tenant_id: uuid.UUID
    ) -> int: ...

    async def get_balance(
        self, employee_id: uuid.UUID, leave_type: str, *, tenant_id: uuid.UUID
    ) -> ent.LeaveBalance | None: ...

    async def approved_unpaid_days(
        self,
        employee_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> int:
        """LeaveLedgerPort read: approved ``unpaid`` leave days in a period (Rule 9)."""
        ...

    async def list_balances(
        self, employee_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Sequence[ent.LeaveBalance]: ...

    async def upsert_balance(self, balance: ent.LeaveBalance) -> ent.LeaveBalance: ...

    # --- Leave requests ---
    async def create_leave_request(self, request: ent.LeaveRequest) -> ent.LeaveRequest: ...

    async def get_leave_request(
        self, request_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ent.LeaveRequest | None: ...

    async def update_leave_request(self, request: ent.LeaveRequest) -> ent.LeaveRequest: ...

    async def transition_leave_status(
        self,
        request_id: uuid.UUID,
        from_status: str,
        to_status: str,
        *,
        tenant_id: uuid.UUID,
        approved_by: uuid.UUID | None = None,
        approved_at: object | None = None,
    ) -> ent.LeaveRequest | None: ...

    async def list_leave_requests(
        self,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        employee_id: uuid.UUID | None = None,
        from_date: object | None = None,
        to_date: object | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[ent.LeaveRequest]: ...

    # --- Compensation (recorded at hire; owned by payroll repo at read time) ---
    async def create_compensation(self, compensation: ent.Compensation) -> ent.Compensation: ...

    async def get_compensation(
        self,
        employee_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        effective_for: date,
    ) -> ent.Compensation | None: ...

    # --- Attendance (one row per employee per work day) ---
    async def upsert_attendance_record(self, record: ent.AttendanceRecord) -> ent.AttendanceRecord: ...

    async def get_attendance_record(
        self, employee_id: uuid.UUID, work_date: date, *, tenant_id: uuid.UUID
    ) -> ent.AttendanceRecord | None: ...

    async def list_attendance_with_employee(
        self,
        tenant_id: uuid.UUID,
        *,
        employee_id: uuid.UUID | None = None,
        status: str | None = None,
        date_from: object | None = None,
        date_to: object | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[tuple[ent.AttendanceRecord, str, str, str]]: ...


class HrServiceDeps(Protocol):
    """HrService dependencies — repository, audit, and the identity validator."""

    @property
    def repositories(self) -> HrRepositoryPort: ...

    @property
    def audit(self) -> object: ...

    @property
    def identity(self) -> IdentityUserPort: ...


__all__ = ["HrRepositoryPort", "HrServiceDeps", "IdentityUserPort"]
