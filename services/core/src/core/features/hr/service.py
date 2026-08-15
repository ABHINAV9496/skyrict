"""HR service — departments, employees, leave rules 1-6 (docs/hr-payroll.md §4).

Pure-logic phase: services depend on :class:`HrRepositoryPort` /
:class:`IdentityUserPort` protocols and the shared :class:`AuditService`;
concurrency (atomic conditional UPDATE, RLS) stays in the deferred
integration suite. Events are emitted AFTER a successful repository write via
module-level producers (docs §2.5).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from core.core import audit_events
from core.core.audit_service import AuditService
from core.core.constants import EmploymentStatus, LeaveRequestStatus
from core.core.exceptions import (
    DuplicateRecordError,
    EmployeeTerminatedError,
    IllegalStateTransitionError,
    LeaveBalanceExceededError,
    SelfApprovalForbiddenError,
)
from core.core.state_machine import InvalidTransitionError, StateMachine
from core.domain import entities as ent
from core.domain.value_objects import Money
from core.events.producers.hr_events import (
    emit_department_created,
    emit_department_updated,
    emit_employee_created,
    emit_employee_onboarded,
    emit_employee_terminated,
    emit_employee_updated,
    emit_leave_accrued,
    emit_leave_approved,
    emit_leave_balance_adjusted,
    emit_leave_cancelled,
    emit_leave_rejected,
    emit_leave_requested,
)
from core.features.hr.ports import HrRepositoryPort, IdentityUserPort

# State machines (docs §3.3).
_EMPLOYEE_MACHINE = StateMachine(
    {
        EmploymentStatus.ACTIVE: (EmploymentStatus.ON_LEAVE, EmploymentStatus.TERMINATED),
        EmploymentStatus.ON_LEAVE: (EmploymentStatus.ACTIVE,),
        EmploymentStatus.TERMINATED: (),
    },
    entity="employee",
)

_LEAVE_MACHINE = StateMachine(
    {
        LeaveRequestStatus.PENDING: (
            LeaveRequestStatus.APPROVED,
            LeaveRequestStatus.REJECTED,
            LeaveRequestStatus.CANCELLED,
        ),
        LeaveRequestStatus.APPROVED: (LeaveRequestStatus.CANCELLED,),
        LeaveRequestStatus.REJECTED: (),
        LeaveRequestStatus.CANCELLED: (),
    },
    entity="leave request",
)


def _require_id(entity: ent.Employee, what: str) -> uuid.UUID:
    """Return a persisted entity's id, which must always be set."""
    if entity.id is None:
        raise ValueError(f"persisted {what} is missing an id")
    return entity.id


class DepartmentService:
    """Department CRUD — tenant-scoped, soft-disable via ``is_active``."""

    def __init__(self, repository: HrRepositoryPort, audit: AuditService) -> None:
        self._repo = repository
        self._audit = audit

    @property
    def repository(self) -> HrRepositoryPort:
        return self._repo

    async def create(
        self,
        *,
        name: str,
        tenant_id: uuid.UUID,
        manager_employee_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.Department:
        department = ent.Department(
            tenant_id=tenant_id,
            name=name,
            manager_employee_id=manager_employee_id,
            is_active=True,
            id=uuid.uuid4(),
        )
        try:
            created = await self._repo.create_department(department)
        except Exception as exc:  # DB unique (tenant, name) violation surfaces here.
            if _is_unique_violation(exc):
                raise DuplicateRecordError(f"department {name!r} already exists") from exc
            raise
        await self._audit.log(
            action=audit_events.HR_DEPARTMENT_CREATED,
            target=f"department:{created.id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
        )
        if created.id is not None:
            await emit_department_created(
                department_id=created.id, tenant_id=tenant_id, name=created.name
            )
        return created

    async def get(self, department_id: uuid.UUID, *, tenant_id: uuid.UUID) -> ent.Department | None:
        return await self._repo.get_department(department_id, tenant_id)

    async def update(
        self, department: ent.Department, *, actor_user_id: uuid.UUID | None = None
    ) -> ent.Department:
        if department.id is None:
            raise ValueError("cannot update a department without an id")
        existing = await self._repo.get_department(department.id, department.tenant_id)
        if existing is None:
            raise ValueError(f"department {department.id} not found")
        updated = await self._repo.update_department(department)
        changed: dict[str, object] = {}
        for field_name in ("name", "manager_employee_id", "is_active"):
            old_value = getattr(existing, field_name)
            new_value = getattr(department, field_name)
            if new_value != old_value:
                changed[field_name] = (
                    str(new_value) if isinstance(new_value, uuid.UUID) else new_value
                )
        await self._audit.log(
            action=audit_events.HR_DEPARTMENT_UPDATED,
            target=f"department:{updated.id}",
            tenant_id=updated.tenant_id,
            user_id=actor_user_id,
            details=changed,
        )
        if updated.id is not None:
            await emit_department_updated(
                department_id=updated.id,
                tenant_id=updated.tenant_id,
                changed_fields=changed,
            )
        return updated

    async def list(
        self, tenant_id: uuid.UUID, *, include_inactive: bool = False
    ) -> list[ent.Department]:
        return list(await self._repo.list_departments(tenant_id, include_inactive=include_inactive))


class EmployeeService:
    """Employee lifecycle — hire, update, status transitions, terminate (rules via §3.3)."""

    def __init__(
        self, repository: HrRepositoryPort, audit: AuditService, identity: IdentityUserPort
    ) -> None:
        self._repo = repository
        self._audit = audit
        self._identity = identity

    @property
    def repository(self) -> HrRepositoryPort:
        return self._repo

    async def hire(
        self,
        *,
        tenant_id: uuid.UUID,
        first_name: str,
        last_name: str,
        email: str | None = None,
        phone: str | None = None,
        job_title: str,
        hire_date: date,
        department_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        monthly_salary: Money | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.Employee:
        """Create an employee (active), record starting compensation if given,
        and accrue annual leave pro-rata from the hire date."""
        if user_id is not None:
            await self._identity.validate_user(user_id, tenant_id=tenant_id)

        number = await self._repo.next_employee_number(tenant_id)
        employee = ent.Employee(
            tenant_id=tenant_id,
            employee_number=f"EMP-{number}",
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            job_title=job_title,
            hire_date=hire_date,
            department_id=department_id,
            user_id=user_id,
            employment_status=EmploymentStatus.ACTIVE,
            id=uuid.uuid4(),
        )
        created = await self._repo.create_employee(employee)

        if monthly_salary is not None:
            await self._repo.create_compensation(
                ent.Compensation(
                    tenant_id=tenant_id,
                    employee_id=_require_id(created, "employee"),
                    monthly_salary=monthly_salary,
                    effective_from=hire_date,
                    is_active=True,
                    id=uuid.uuid4(),
                )
            )

        # Rule 4: pro-rata annual accrual on hire (same transaction in DB phase).
        leave = await self._accrue_annual(created, year=hire_date.year, tenant_id=tenant_id)

        await self._audit.log(
            action=audit_events.HR_EMPLOYEE_CREATED,
            target=f"employee:{created.id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={
                "employee_number": created.employee_number,
                "hire_date": hire_date.isoformat(),
            },
        )
        if created.id is not None:
            await emit_employee_created(
                employee_id=created.id,
                employee_number=created.employee_number,
                department_id=created.department_id,
                status=created.employment_status.value,
                tenant_id=tenant_id,
            )
            await emit_employee_onboarded(
                employee_id=created.id,
                hire_date=hire_date.isoformat(),
                department_id=created.department_id,
                tenant_id=tenant_id,
            )
            if leave is not None and leave.id is not None:
                await emit_leave_accrued(
                    employee_id=created.id,
                    leave_type=leave.leave_type,
                    leave_year=hire_date.year,
                    qty=leave.qty,
                    tenant_id=tenant_id,
                )
        return created

    async def _accrue_annual(
        self, employee: ent.Employee, *, year: int, tenant_id: uuid.UUID
    ) -> ent.LeaveMovement | None:
        leave_type = await self._repo.get_leave_type("annual", tenant_id=tenant_id)
        if (
            leave_type is None
            or not leave_type.is_accrual
            or leave_type.accrual_days_per_year is None
        ):
            return None
        remaining = _remaining_days_in_year(employee.hire_date, year)
        qty = _round_half_up(
            Decimal(leave_type.accrual_days_per_year) * Decimal(remaining) / Decimal(365)
        )
        if qty < 1:
            return None
        return await self._repo.accrue_leave_movement(
            ent.LeaveMovement(
                tenant_id=tenant_id,
                employee_id=_require_id(employee, "employee"),
                leave_type="annual",
                qty=qty,
                ref_type="annual_accrual",
                ref_id=str(year),
                id=uuid.uuid4(),
            )
        )

    async def get(self, employee_id: uuid.UUID, *, tenant_id: uuid.UUID) -> ent.Employee | None:
        return await self._repo.get_employee(employee_id, tenant_id)

    async def get_active_compensation(
        self, employee_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> ent.Compensation | None:
        """The employee's current (as-of today) active compensation record."""
        return await self._repo.get_compensation(
            employee_id, tenant_id=tenant_id, effective_for=date.today()
        )

    async def update(
        self,
        employee: ent.Employee,
        *,
        changed_fields: list[str],
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.Employee:
        """Update employee details; not allowed on terminated employees."""
        if employee.employment_status == EmploymentStatus.TERMINATED:
            raise EmployeeTerminatedError("cannot update a terminated employee")
        updated = await self._repo.update_employee(employee)
        await self._audit.log(
            action=audit_events.HR_EMPLOYEE_UPDATED,
            target=f"employee:{updated.id}",
            tenant_id=updated.tenant_id,
            user_id=actor_user_id,
            details={"fields": changed_fields},
        )
        if updated.id is not None:
            await emit_employee_updated(
                employee_id=updated.id,
                tenant_id=updated.tenant_id,
                changed_fields={field: getattr(updated, field) for field in changed_fields},
            )
        return updated

    async def change_status(
        self,
        *,
        employee_id: uuid.UUID,
        tenant_id: uuid.UUID,
        new_status: EmploymentStatus,
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.Employee:
        """Set status transition among active ⇄ on_leave (never to terminated here)."""
        employee = await self._repo.get_employee(employee_id, tenant_id)
        if employee is None:
            raise ValueError(f"employee {employee_id} not found")
        if new_status == EmploymentStatus.TERMINATED:
            raise ValueError("use terminate() to terminate an employee")
        if employee.employment_status == EmploymentStatus.TERMINATED:
            raise EmployeeTerminatedError("cannot change status of a terminated employee")
        try:
            _EMPLOYEE_MACHINE.transition(employee.employment_status.value, new_status.value)
        except InvalidTransitionError as exc:
            raise IllegalStateTransitionError(str(exc)) from exc
        updated = dataclasses.replace(
            employee,
            employment_status=new_status,
            termination_date=employee.termination_date,
        )
        updated = await self._repo.update_employee(updated)
        await self._audit.log(
            action=audit_events.HR_EMPLOYEE_UPDATED,
            target=f"employee:{updated.id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={"fields": ["employment_status"], "status": new_status.value},
        )
        if updated.id is not None:
            await emit_employee_updated(
                employee_id=updated.id,
                tenant_id=tenant_id,
                changed_fields={"employment_status": new_status.value},
            )
        return updated

    async def terminate(
        self,
        *,
        employee_id: uuid.UUID,
        tenant_id: uuid.UUID,
        termination_date: date,
        reason: str | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.Employee:
        """Terminate only from active; termination_date required (DB CHECK)."""
        employee = await self._repo.get_employee(employee_id, tenant_id)
        if employee is None:
            raise ValueError(f"employee {employee_id} not found")
        if employee.employment_status != EmploymentStatus.ACTIVE:
            raise IllegalStateTransitionError("only active employees can be terminated")
        if termination_date < employee.hire_date:
            raise ValueError("termination date cannot precede hire date")
        updated = dataclasses.replace(
            employee,
            employment_status=EmploymentStatus.TERMINATED,
            termination_date=termination_date,
        )
        updated = await self._repo.update_employee(updated)
        await self._audit.log(
            action=audit_events.HR_EMPLOYEE_TERMINATED,
            target=f"employee:{updated.id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={"termination_date": termination_date.isoformat(), "reason": reason},
        )
        if updated.id is not None:
            await emit_employee_terminated(
                employee_id=updated.id,
                termination_date=termination_date.isoformat(),
                tenant_id=tenant_id,
            )
        return updated

    async def list(
        self,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        department_id: uuid.UUID | None = None,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ent.Employee]:
        return list(
            await self._repo.list_employees(
                tenant_id,
                status=status,
                department_id=department_id,
                q=q,
                limit=limit,
                offset=offset,
            )
        )


class LeaveService:
    """Leave lifecycle — rules 1-6: approve, balance, atomicity, accrual, cancel, self-approval."""

    def __init__(self, repository: HrRepositoryPort, audit: AuditService) -> None:
        self._repo = repository
        self._audit = audit

    @property
    def repository(self) -> HrRepositoryPort:
        return self._repo

    async def request(
        self,
        *,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID,
        leave_type: str,
        start_date: date,
        end_date: date,
        reason: str | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.LeaveRequest:
        """Create a pending request; days computed server-side."""
        if end_date < start_date:
            raise ValueError("end_date cannot precede start_date")
        days = (end_date - start_date).days + 1
        leave_type_row = await self._repo.get_leave_type(leave_type, tenant_id=tenant_id)
        if leave_type_row is None:
            raise ValueError(f"unknown leave type {leave_type!r}")
        employee = await self._repo.get_employee(employee_id, tenant_id)
        if employee is None:
            raise ValueError(f"employee {employee_id} not found")
        if employee.employment_status == EmploymentStatus.TERMINATED:
            raise EmployeeTerminatedError("terminated employees cannot request leave")
        request = ent.LeaveRequest(
            tenant_id=tenant_id,
            employee_id=employee_id,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            days=days,
            status=LeaveRequestStatus.PENDING,
            reason=reason,
            id=uuid.uuid4(),
        )
        created = await self._repo.create_leave_request(request)
        await self._audit.log(
            action=audit_events.HR_LEAVE_REQUESTED,
            target=f"leave_request:{created.id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={"days": created.days, "leave_type": created.leave_type},
        )
        if created.id is not None:
            await emit_leave_requested(
                request_id=created.id,
                employee_id=created.employee_id,
                leave_type=created.leave_type,
                days=created.days,
                tenant_id=tenant_id,
            )
        return created

    async def approve(
        self,
        *,
        request_id: uuid.UUID,
        tenant_id: uuid.UUID,
        approved_by: uuid.UUID,
        actor_user_id: uuid.UUID | None = None,
    ) -> tuple[ent.LeaveRequest, int]:
        """Rule 1 + Rule 2 + Rule 3 + Rule 6: approve a pending request."""
        request = await self._repo.get_leave_request(request_id, tenant_id)
        if request is None:
            raise ValueError(f"leave request {request_id} not found")

        # Rule 3 (docs §4.3): only active employees may have leave approved.
        employee = await self._repo.get_employee(request.employee_id, tenant_id)
        if employee is None:
            raise ValueError(f"employee {request.employee_id} not found")
        if employee.employment_status == EmploymentStatus.TERMINATED:
            raise EmployeeTerminatedError("cannot approve leave for a terminated employee")

        # Rule 6: approver != requester.
        if approved_by == request.employee_id:
            raise SelfApprovalForbiddenError("cannot approve your own leave request")

        try:
            _LEAVE_MACHINE.transition(request.status.value, LeaveRequestStatus.APPROVED.value)
        except InvalidTransitionError:
            # Rule 1 idempotence: re-approve on already-approved is a no-op.
            if request.status == LeaveRequestStatus.APPROVED:
                balance = await self._repo.recompute_balance(
                    request.employee_id, request.leave_type, tenant_id=tenant_id
                )
                return request, balance
            raise IllegalStateTransitionError("leave request is not pending") from None

        # Rule 2: negative balance rejected at service layer BEFORE any write.
        leave_type_row = await self._repo.get_leave_type(request.leave_type, tenant_id=tenant_id)
        is_accrual = leave_type_row is not None and leave_type_row.is_accrual
        if is_accrual:
            # Rule 3 (docs §4.3): row-lock the employee's balance bucket BEFORE
            # the balance read, inside this transaction. Two concurrent approves
            # of different requests for the same employee serialize here: the
            # loser re-reads the committed ledger and the Rule 2 check rejects
            # it, so the ledger can never go negative and the materialized
            # balance can never drift from it. LOCK-ORDERING: exactly one row,
            # so no deadlock cycle is possible with any multi-row caller.
            await self._repo.lock_leave_balance(
                request.employee_id, request.leave_type, tenant_id=tenant_id
            )
            current_balance = await self._repo.recompute_balance(
                request.employee_id, request.leave_type, tenant_id=tenant_id
            )
            projected = current_balance - request.days
            if projected < 0:
                raise LeaveBalanceExceededError(
                    f"approving {request.days} days would drive balance below zero"
                )

        # Rule 3: atomic guard — transition returns None if the row wasn't pending.
        transitioned = await self._repo.transition_leave_status(
            request_id,
            LeaveRequestStatus.PENDING.value,
            LeaveRequestStatus.APPROVED.value,
            tenant_id=tenant_id,
            approved_by=approved_by,
            approved_at=datetime.now(UTC),
        )
        if transitioned is None:
            # Concurrent approve won (guard) — re-read and treat as already-approved.
            current = await self._repo.get_leave_request(request_id, tenant_id)
            if current is None:
                raise ValueError(f"leave request {request_id} not found")
            return current, await self._repo.recompute_balance(
                current.employee_id, current.leave_type, tenant_id=tenant_id
            )

        # Rule 1: write -days movement + recompute + seed balance (only accrual).
        await self._repo.add_leave_movement(
            ent.LeaveMovement(
                tenant_id=tenant_id,
                employee_id=request.employee_id,
                leave_type=request.leave_type,
                qty=-request.days,
                ref_type="approval",
                ref_id=str(request_id),
                id=uuid.uuid4(),
            )
        )
        new_balance = await self._repo.recompute_balance(
            request.employee_id, request.leave_type, tenant_id=tenant_id
        )
        if is_accrual:
            await self._repo.upsert_balance(
                ent.LeaveBalance(
                    tenant_id=tenant_id,
                    employee_id=request.employee_id,
                    leave_type=request.leave_type,
                    balance=new_balance,
                    id=uuid.uuid4(),
                )
            )

        await self._audit.log(
            action=audit_events.HR_LEAVE_APPROVED,
            target=f"leave_request:{request_id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={
                "days": request.days,
                "leave_type": request.leave_type,
                "new_balance": new_balance,
            },
        )
        if transitioned.id is not None:
            await emit_leave_approved(
                request_id=request_id,
                employee_id=request.employee_id,
                leave_type=request.leave_type,
                days=request.days,
                tenant_id=tenant_id,
            )
        return transitioned, new_balance

    async def reject(
        self,
        *,
        request_id: uuid.UUID,
        tenant_id: uuid.UUID,
        reason: str | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.LeaveRequest:
        request = await self._repo.get_leave_request(request_id, tenant_id)
        if request is None:
            raise ValueError(f"leave request {request_id} not found")
        try:
            _LEAVE_MACHINE.transition(request.status.value, LeaveRequestStatus.REJECTED.value)
        except InvalidTransitionError:
            raise IllegalStateTransitionError("only pending requests can be rejected") from None
        transitioned = await self._repo.transition_leave_status(
            request_id,
            LeaveRequestStatus.PENDING.value,
            LeaveRequestStatus.REJECTED.value,
            tenant_id=tenant_id,
        )
        if transitioned is None:
            raise IllegalStateTransitionError("leave request is not pending")
        await self._audit.log(
            action=audit_events.HR_LEAVE_REJECTED,
            target=f"leave_request:{request_id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={"reason": reason},
        )
        if transitioned.id is not None:
            await emit_leave_rejected(
                request_id=request_id,
                employee_id=transitioned.employee_id,
                reason=reason,
                tenant_id=tenant_id,
            )
        return transitioned

    async def cancel(
        self,
        *,
        request_id: uuid.UUID,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None = None,
    ) -> tuple[ent.LeaveRequest, int]:
        """Rule 5: cancel from pending (no-op) or approved (+days reversal)."""
        request = await self._repo.get_leave_request(request_id, tenant_id)
        if request is None:
            raise ValueError(f"leave request {request_id} not found")
        try:
            _LEAVE_MACHINE.transition(request.status.value, LeaveRequestStatus.CANCELLED.value)
        except InvalidTransitionError:
            raise IllegalStateTransitionError(
                "only pending or approved requests can be cancelled"
            ) from None

        if request.status == LeaveRequestStatus.PENDING:
            return await self._cancel_pending(
                request=request,
                request_id=request_id,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
            )

        leave_type_row = await self._repo.get_leave_type(request.leave_type, tenant_id=tenant_id)
        is_accrual = leave_type_row is not None and leave_type_row.is_accrual
        if is_accrual:
            # Rule 3 (docs §4.3): same balance-row lock as approve — the reversal
            # below also reads-then-writes the balance, so a concurrent approval
            # must serialize against it rather than compute a stale ledger view.
            await self._repo.lock_leave_balance(
                request.employee_id, request.leave_type, tenant_id=tenant_id
            )

        transitioned = await self._repo.transition_leave_status(
            request_id,
            LeaveRequestStatus.APPROVED.value,
            LeaveRequestStatus.CANCELLED.value,
            tenant_id=tenant_id,
        )
        if transitioned is None:
            raise IllegalStateTransitionError("leave request is not approved")

        await self._repo.add_leave_movement(
            ent.LeaveMovement(
                tenant_id=tenant_id,
                employee_id=request.employee_id,
                leave_type=request.leave_type,
                qty=request.days,
                ref_type="cancellation",
                ref_id=str(request_id),
                id=uuid.uuid4(),
            )
        )
        new_balance = await self._repo.recompute_balance(
            request.employee_id, request.leave_type, tenant_id=tenant_id
        )
        if is_accrual:
            await self._repo.upsert_balance(
                ent.LeaveBalance(
                    tenant_id=tenant_id,
                    employee_id=request.employee_id,
                    leave_type=request.leave_type,
                    balance=new_balance,
                    id=uuid.uuid4(),
                )
            )

        await self._audit.log(
            action=audit_events.HR_LEAVE_CANCELLED,
            target=f"leave_request:{request_id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={
                "days": request.days,
                "leave_type": request.leave_type,
                "new_balance": new_balance,
            },
        )
        if transitioned.id is not None:
            await emit_leave_cancelled(
                request_id=request_id,
                employee_id=request.employee_id,
                leave_type=request.leave_type,
                days=request.days,
                tenant_id=tenant_id,
            )
        return transitioned, new_balance

    async def _cancel_pending(
        self,
        *,
        request: ent.LeaveRequest,
        request_id: uuid.UUID,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
    ) -> tuple[ent.LeaveRequest, int]:
        """Cancel a pending request: transition only, no ledger movement (gap #1).

        A pending request has written nothing to the ledger, so there is no
        reversal to post; this is a plain status transition (docs §4.5).
        """
        transitioned = await self._repo.transition_leave_status(
            request_id,
            LeaveRequestStatus.PENDING.value,
            LeaveRequestStatus.CANCELLED.value,
            tenant_id=tenant_id,
        )
        if transitioned is None:
            raise IllegalStateTransitionError("leave request is not pending")
        new_balance = await self._repo.recompute_balance(
            request.employee_id, request.leave_type, tenant_id=tenant_id
        )
        await self._audit.log(
            action=audit_events.HR_LEAVE_CANCELLED,
            target=f"leave_request:{request_id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={
                "days": request.days,
                "leave_type": request.leave_type,
                "new_balance": new_balance,
            },
        )
        if transitioned.id is not None:
            await emit_leave_cancelled(
                request_id=request_id,
                employee_id=request.employee_id,
                leave_type=request.leave_type,
                days=request.days,
                tenant_id=tenant_id,
            )
        return transitioned, new_balance

    async def adjust_balance(
        self,
        *,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID,
        leave_type: str,
        qty: int,
        reason: str,
        actor_user_id: uuid.UUID | None = None,
    ) -> int:
        """Manual balance adjustment (override) — ledger write + recompute."""
        if qty == 0:
            raise ValueError("adjustment quantity cannot be zero")
        leave_type_row = await self._repo.get_leave_type(leave_type, tenant_id=tenant_id)
        if leave_type_row is None:
            raise ValueError(f"unknown leave type {leave_type!r}")
        await self._repo.add_leave_movement(
            ent.LeaveMovement(
                tenant_id=tenant_id,
                employee_id=employee_id,
                leave_type=leave_type,
                qty=qty,
                ref_type="adjustment",
                ref_id=None,
                reason=reason,
                id=uuid.uuid4(),
            )
        )
        new_balance = await self._repo.recompute_balance(
            employee_id, leave_type, tenant_id=tenant_id
        )
        if leave_type_row.is_accrual:
            await self._repo.upsert_balance(
                ent.LeaveBalance(
                    tenant_id=tenant_id,
                    employee_id=employee_id,
                    leave_type=leave_type,
                    balance=new_balance,
                    id=uuid.uuid4(),
                )
            )
        await self._audit.log(
            action=audit_events.HR_LEAVE_BALANCE_ADJUSTED,
            target=f"employee:{employee_id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={
                "leave_type": leave_type,
                "qty": qty,
                "reason": reason,
                "new_balance": new_balance,
            },
        )
        await emit_leave_balance_adjusted(
            employee_id=employee_id,
            leave_type=leave_type,
            qty=qty,
            reason=reason,
            tenant_id=tenant_id,
        )
        return new_balance

    async def accrue(
        self,
        *,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID,
        leave_type: str,
        year: int,
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.LeaveMovement | None:
        """Rule 4: idempotent annual accrual per (employee, leave_type, leave_year)."""
        leave_type_row = await self._repo.get_leave_type(leave_type, tenant_id=tenant_id)
        if leave_type_row is None:
            raise ValueError(f"unknown leave type {leave_type!r}")
        if not leave_type_row.is_accrual or leave_type_row.accrual_days_per_year is None:
            raise ValueError(f"leave type {leave_type!r} does not accrue")
        employee = await self._repo.get_employee(employee_id, tenant_id)
        if employee is None:
            raise ValueError(f"employee {employee_id} not found")
        remaining = _remaining_days_in_year(employee.hire_date, year)
        qty = _round_half_up(
            Decimal(leave_type_row.accrual_days_per_year) * Decimal(remaining) / Decimal(365)
        )
        if qty < 1:
            return None
        movement = await self._repo.accrue_leave_movement(
            ent.LeaveMovement(
                tenant_id=tenant_id,
                employee_id=employee_id,
                leave_type=leave_type,
                qty=qty,
                ref_type="annual_accrual",
                ref_id=str(year),
                id=uuid.uuid4(),
            )
        )
        if movement is None:
            return None  # idempotent: already accrued for (employee, type, year).
        await self._audit.log(
            action=audit_events.HR_LEAVE_ACCRUED,
            target=f"employee:{employee_id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={"leave_type": leave_type, "year": year, "qty": qty},
        )
        if movement.id is not None:
            await emit_leave_accrued(
                employee_id=employee_id,
                leave_type=leave_type,
                leave_year=year,
                qty=qty,
                tenant_id=tenant_id,
            )
        return movement

    async def list_leave_requests(
        self,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        employee_id: uuid.UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ent.LeaveRequest]:
        return list(
            await self._repo.list_leave_requests(
                tenant_id,
                status=status,
                employee_id=employee_id,
                from_date=from_date,
                to_date=to_date,
                limit=limit,
                offset=offset,
            )
        )

    async def get(self, request_id: uuid.UUID, *, tenant_id: uuid.UUID) -> ent.LeaveRequest | None:
        """Fetch one leave request by id."""
        return await self._repo.get_leave_request(request_id, tenant_id)

    async def list_balances(
        self, employee_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> list[ent.LeaveBalance]:
        """All materialized leave balances for one employee, by leave type."""
        return list(await self._repo.list_balances(employee_id, tenant_id=tenant_id))

    async def list_movements(
        self,
        employee_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        leave_type: str | None = None,
    ) -> list[ent.LeaveMovement]:
        """The leave ledger history for one employee, optionally filtered by type."""
        return list(
            await self._repo.list_leave_movements(tenant_id, employee_id, leave_type=leave_type)
        )

    async def approved_unpaid_days(
        self,
        employee_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> int:
        """LeaveLedgerPort read: approved ``unpaid`` leave days in a period (Rule 9)."""
        return await self._repo.approved_unpaid_days(
            employee_id, tenant_id=tenant_id, period_start=period_start, period_end=period_end
        )

    async def list_accrual_leave_types(self, tenant_id: uuid.UUID) -> list[str]:
        """LeaveLedgerPort read: leave types that accrue annually (Rule 4)."""
        return list(await self._repo.list_accrual_leave_types(tenant_id))


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _remaining_days_in_year(hire_date: date, year: int) -> int:
    if year > hire_date.year:
        return 365
    return 365 - (hire_date.timetuple().tm_yday - 1)


def _is_unique_violation(exc: Exception) -> bool:
    """True for PostgreSQL unique-violation (SQLSTATE 23505).

    asyncpg surfaces the SQLSTATE on ``orig.sqlstate`` but omits it from the
    message text, so a message scan alone misses it (the string only carries
    the constraint name). psycopg embeds the code in the message instead.
    """
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    sqlstate = getattr(orig, "sqlstate", None)
    if sqlstate is not None:
        return bool(sqlstate == "23505")
    return "23505" in str(orig)


__all__ = ["DepartmentService", "EmployeeService", "LeaveService"]
