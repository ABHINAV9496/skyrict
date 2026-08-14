"""HR repository — DB operations for departments, employees, leave ledger & balances.

The leave ledger mirrors the inventory stock ledger: movements are immutable
append-only rows, and balances are recomputed from the ledger and materialized
into ``erp_leave_balances`` in the SAME transaction. The balance CHECK
(``balance >= 0``) is evaluated by the database when the materialized row is
written, so a negative-balance write fails the whole transaction — including
the movement insert — independent of service logic (docs §4.2, Rule 2).

``accrue_leave_movement`` is idempotent per ``(tenant_id, employee_id,
leave_type, ref_type='annual_accrual', ref_id=<leave_year>)`` (docs §4.4,
Rule 4): if the annual grant already exists the probe returns ``None`` and
nothing is written. On a fresh grant it writes the movement AND recomputes +
materializes the balance, because the service never materializes accruals
separately (``hire`` / ``accrue`` rely on this repository to do so).

All probes are tenant-scoped: lookups take an explicit ``tenant_id`` and every
session is additionally bound by RLS (``app.current_tenant_id``), so a tenant
can never read or write another tenant's rows at either layer. This repository
also implements the payroll ``LeaveLedgerPort.approved_unpaid_days`` read — the
one sanctioned cross-feature read — so it can be injected as the leave ledger
at the composition root.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.core.constants import EmploymentStatus, LeaveRequestStatus
from core.domain import entities as ent
from core.domain.value_objects import Money
from core.features.hr.models.department import DepartmentModel
from core.features.hr.models.employee import (
    EmployeeModel,
)
from core.features.hr.models.employee import (
    EmploymentStatus as EmployeeEmploymentStatus,
)
from core.features.hr.models.leave_balance import LeaveBalanceModel
from core.features.hr.models.leave_movement import LeaveMovementModel
from core.features.hr.models.leave_request import LeaveRequestModel
from core.features.hr.models.leave_request import (
    LeaveRequestStatus as LeaveRequestStatusModel,
)
from core.features.hr.models.leave_type import LeaveTypeModel
from core.features.payroll.models.compensation import CompensationModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_ANNUAL_ACCRUAL = "annual_accrual"
_UNPAID_LEAVE = "unpaid"


def _department_to_orm(department: ent.Department) -> DepartmentModel:
    kwargs: dict[str, object] = {
        "tenant_id": department.tenant_id,
        "name": department.name,
        "manager_employee_id": department.manager_employee_id,
        "is_active": department.is_active,
    }
    if department.id is not None:
        kwargs["id"] = department.id
    return DepartmentModel(**kwargs)


def _department_from_orm(model: DepartmentModel) -> ent.Department:
    return ent.Department(
        id=model.id,
        tenant_id=model.tenant_id,
        name=model.name,
        manager_employee_id=model.manager_employee_id,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _employee_to_orm(employee: ent.Employee) -> EmployeeModel:
    kwargs: dict[str, object] = {
        "tenant_id": employee.tenant_id,
        "employee_number": employee.employee_number,
        "first_name": employee.first_name,
        "last_name": employee.last_name,
        "email": employee.email,
        "phone": employee.phone,
        "user_id": employee.user_id,
        "department_id": employee.department_id,
        "job_title": employee.job_title,
        "employment_status": EmployeeEmploymentStatus(employee.employment_status.value),
        "hire_date": employee.hire_date,
        "termination_date": employee.termination_date,
    }
    if employee.id is not None:
        kwargs["id"] = employee.id
    return EmployeeModel(**kwargs)


def _employee_from_orm(model: EmployeeModel) -> ent.Employee:
    return ent.Employee(
        id=model.id,
        tenant_id=model.tenant_id,
        employee_number=model.employee_number,
        first_name=model.first_name,
        last_name=model.last_name,
        email=model.email,
        phone=model.phone,
        user_id=model.user_id,
        department_id=model.department_id,
        job_title=model.job_title,
        employment_status=EmploymentStatus(model.employment_status.value),
        hire_date=model.hire_date,
        termination_date=model.termination_date,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _leave_type_from_orm(model: LeaveTypeModel) -> ent.LeaveType:
    return ent.LeaveType(
        id=model.id,
        tenant_id=model.tenant_id,
        code=model.code,
        name=model.name,
        is_accrual=model.is_accrual,
        accrual_days_per_year=model.accrual_days_per_year,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _leave_request_to_orm(request: ent.LeaveRequest) -> LeaveRequestModel:
    kwargs: dict[str, object] = {
        "tenant_id": request.tenant_id,
        "employee_id": request.employee_id,
        "leave_type": request.leave_type,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "days": request.days,
        "status": LeaveRequestStatusModel(request.status.value),
        "reason": request.reason,
        "approved_by": request.approved_by,
        "approved_at": request.approved_at,
    }
    if request.id is not None:
        kwargs["id"] = request.id
    return LeaveRequestModel(**kwargs)


def _leave_request_from_orm(model: LeaveRequestModel) -> ent.LeaveRequest:
    return ent.LeaveRequest(
        id=model.id,
        tenant_id=model.tenant_id,
        employee_id=model.employee_id,
        leave_type=model.leave_type,
        start_date=model.start_date,
        end_date=model.end_date,
        days=model.days,
        status=LeaveRequestStatus(model.status.value),
        reason=model.reason,
        approved_by=model.approved_by,
        approved_at=model.approved_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _leave_movement_to_orm(movement: ent.LeaveMovement) -> LeaveMovementModel:
    kwargs: dict[str, object] = {
        "tenant_id": movement.tenant_id,
        "employee_id": movement.employee_id,
        "leave_type": movement.leave_type,
        "qty": movement.qty,
        "ref_type": movement.ref_type,
        "ref_id": movement.ref_id,
        "reason": movement.reason,
    }
    if movement.id is not None:
        kwargs["id"] = movement.id
    return LeaveMovementModel(**kwargs)


def _leave_movement_from_orm(model: LeaveMovementModel) -> ent.LeaveMovement:
    return ent.LeaveMovement(
        id=model.id,
        tenant_id=model.tenant_id,
        employee_id=model.employee_id,
        leave_type=model.leave_type,
        qty=model.qty,
        ref_type=model.ref_type,
        ref_id=model.ref_id,
        reason=model.reason,
        occurred_at=model.occurred_at,
    )


def _leave_balance_from_orm(model: LeaveBalanceModel) -> ent.LeaveBalance:
    return ent.LeaveBalance(
        id=model.id,
        tenant_id=model.tenant_id,
        employee_id=model.employee_id,
        leave_type=model.leave_type,
        balance=model.balance,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _compensation_to_orm(compensation: ent.Compensation) -> CompensationModel:
    kwargs: dict[str, object] = {
        "tenant_id": compensation.tenant_id,
        "employee_id": compensation.employee_id,
        "monthly_salary": compensation.monthly_salary.amount,
        "currency": compensation.monthly_salary.currency,
        "effective_from": compensation.effective_from,
        "is_active": compensation.is_active,
    }
    if compensation.id is not None:
        kwargs["id"] = compensation.id
    return CompensationModel(**kwargs)


def _compensation_from_orm(model: CompensationModel) -> ent.Compensation:
    return ent.Compensation(
        id=model.id,
        tenant_id=model.tenant_id,
        employee_id=model.employee_id,
        monthly_salary=Money(model.monthly_salary, model.currency),
        effective_from=model.effective_from,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class HrRepository:
    """Concrete SQLAlchemy implementation of :class:`HrRepositoryPort`.

    ``next_sequence`` is the shared tenant-scoped counter provider (injected at
    the composition root as ``SequenceRepository(session).next_value``) so this
    feature never imports the ``core.db`` layer.
    """

    def __init__(
        self,
        session: AsyncSession,
        next_sequence: Callable[[uuid.UUID, str], Awaitable[int]],
    ) -> None:
        self.session = session
        self._next_sequence = next_sequence

    # ------------------------------------------------------------------
    # Departments
    # ------------------------------------------------------------------

    async def create_department(self, department: ent.Department) -> ent.Department:
        model = _department_to_orm(department)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _department_from_orm(model)

    async def get_department(
        self, department_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ent.Department | None:
        stmt = select(DepartmentModel).where(
            DepartmentModel.tenant_id == tenant_id,
            DepartmentModel.id == department_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _department_from_orm(model) if model is not None else None

    async def update_department(self, department: ent.Department) -> ent.Department:
        if department.id is None:
            raise ValueError("department is missing an id")
        stmt = (
            update(DepartmentModel)
            .where(
                DepartmentModel.tenant_id == department.tenant_id,
                DepartmentModel.id == department.id,
            )
            .values(
                name=department.name,
                manager_employee_id=department.manager_employee_id,
                is_active=department.is_active,
                updated_at=func.now(),
            )
            .returning(DepartmentModel)
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise ValueError(f"department {department.id} not found")
        return _department_from_orm(model)

    async def list_departments(
        self, tenant_id: uuid.UUID, *, include_inactive: bool = False
    ) -> Sequence[ent.Department]:
        stmt = select(DepartmentModel).where(DepartmentModel.tenant_id == tenant_id)
        if not include_inactive:
            stmt = stmt.where(DepartmentModel.is_active.is_(True))
        stmt = stmt.order_by(DepartmentModel.name)
        result = await self.session.execute(stmt)
        return [_department_from_orm(model) for model in result.scalars().all()]

    # ------------------------------------------------------------------
    # Employees
    # ------------------------------------------------------------------

    async def create_employee(self, employee: ent.Employee) -> ent.Employee:
        model = _employee_to_orm(employee)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _employee_from_orm(model)

    async def get_employee(
        self, employee_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ent.Employee | None:
        stmt = select(EmployeeModel).where(
            EmployeeModel.tenant_id == tenant_id,
            EmployeeModel.id == employee_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _employee_from_orm(model) if model is not None else None

    async def update_employee(self, employee: ent.Employee) -> ent.Employee:
        if employee.id is None:
            raise ValueError("employee is missing an id")
        stmt = (
            update(EmployeeModel)
            .where(
                EmployeeModel.tenant_id == employee.tenant_id,
                EmployeeModel.id == employee.id,
            )
            .values(
                employee_number=employee.employee_number,
                first_name=employee.first_name,
                last_name=employee.last_name,
                email=employee.email,
                phone=employee.phone,
                user_id=employee.user_id,
                department_id=employee.department_id,
                job_title=employee.job_title,
                employment_status=EmployeeEmploymentStatus(employee.employment_status.value),
                hire_date=employee.hire_date,
                termination_date=employee.termination_date,
                updated_at=func.now(),
            )
            .returning(EmployeeModel)
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise ValueError(f"employee {employee.id} not found")
        return _employee_from_orm(model)

    async def list_employees(
        self,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        department_id: uuid.UUID | None = None,
        q: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[ent.Employee]:
        stmt = select(EmployeeModel).where(EmployeeModel.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(EmployeeModel.employment_status == status)
        if department_id is not None:
            stmt = stmt.where(EmployeeModel.department_id == department_id)
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    EmployeeModel.first_name.ilike(pattern),
                    EmployeeModel.last_name.ilike(pattern),
                    EmployeeModel.employee_number.ilike(pattern),
                )
            )
        stmt = stmt.order_by(EmployeeModel.employee_number).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return [_employee_from_orm(model) for model in result.scalars().all()]

    async def next_employee_number(self, tenant_id: uuid.UUID) -> int:
        return await self._next_sequence(tenant_id, "employee")

    async def get_employee_by_number(
        self, employee_number: str, tenant_id: uuid.UUID
    ) -> ent.Employee | None:
        stmt = select(EmployeeModel).where(
            EmployeeModel.tenant_id == tenant_id,
            EmployeeModel.employee_number == employee_number,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _employee_from_orm(model) if model is not None else None

    # ------------------------------------------------------------------
    # Leave types
    # ------------------------------------------------------------------

    async def get_leave_type(self, leave_type: str, tenant_id: uuid.UUID) -> ent.LeaveType | None:
        stmt = select(LeaveTypeModel).where(
            LeaveTypeModel.tenant_id == tenant_id,
            LeaveTypeModel.code == leave_type,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _leave_type_from_orm(model) if model is not None else None

    # ------------------------------------------------------------------
    # Leave ledger & balances
    # ------------------------------------------------------------------

    async def add_leave_movement(self, movement: ent.LeaveMovement) -> ent.LeaveMovement:
        """Append one immutable ledger row (idempotency is the caller's job)."""
        model = _leave_movement_to_orm(movement)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _leave_movement_from_orm(model)

    async def list_leave_movements(
        self,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID,
        leave_type: str | None = None,
    ) -> Sequence[ent.LeaveMovement]:
        stmt = select(LeaveMovementModel).where(
            LeaveMovementModel.tenant_id == tenant_id,
            LeaveMovementModel.employee_id == employee_id,
        )
        if leave_type is not None:
            stmt = stmt.where(LeaveMovementModel.leave_type == leave_type)
        stmt = stmt.order_by(LeaveMovementModel.occurred_at.asc())
        result = await self.session.execute(stmt)
        return [_leave_movement_from_orm(model) for model in result.scalars().all()]

    async def accrue_leave_movement(self, movement: ent.LeaveMovement) -> ent.LeaveMovement | None:
        """Idempotent annual accrual: insert + recompute + materialize balance.

        Returns ``None`` when the ``(employee, leave_type, leave_year)`` grant
        already exists (Rule 4). On a fresh grant the movement is written and
        the balance recomputed + materialized in the same transaction.
        """
        existing = await self._find_movement_by_ref(
            movement.employee_id,
            movement.leave_type,
            _ANNUAL_ACCRUAL,
            movement.ref_id,
            movement.tenant_id,
        )
        if existing is not None:
            return None
        await self.add_leave_movement(movement)
        new_balance = await self.recompute_balance(
            movement.employee_id, movement.leave_type, tenant_id=movement.tenant_id
        )
        await self.upsert_balance(
            ent.LeaveBalance(
                tenant_id=movement.tenant_id,
                employee_id=movement.employee_id,
                leave_type=movement.leave_type,
                balance=new_balance,
                id=uuid.uuid4(),
            )
        )
        return movement

    async def recompute_balance(
        self, employee_id: uuid.UUID, leave_type: str, *, tenant_id: uuid.UUID
    ) -> int:
        """Read-side ledger sum — does NOT materialize (Rule 1/§4.1)."""
        stmt = select(func.coalesce(func.sum(LeaveMovementModel.qty), 0)).where(
            LeaveMovementModel.tenant_id == tenant_id,
            LeaveMovementModel.employee_id == employee_id,
            LeaveMovementModel.leave_type == leave_type,
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def get_balance(
        self, employee_id: uuid.UUID, leave_type: str, *, tenant_id: uuid.UUID
    ) -> ent.LeaveBalance | None:
        stmt = select(LeaveBalanceModel).where(
            LeaveBalanceModel.tenant_id == tenant_id,
            LeaveBalanceModel.employee_id == employee_id,
            LeaveBalanceModel.leave_type == leave_type,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _leave_balance_from_orm(model) if model is not None else None

    async def list_balances(
        self, employee_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Sequence[ent.LeaveBalance]:
        """All materialized leave balances for one employee, ordered by type."""
        stmt = (
            select(LeaveBalanceModel)
            .where(
                LeaveBalanceModel.tenant_id == tenant_id,
                LeaveBalanceModel.employee_id == employee_id,
            )
            .order_by(LeaveBalanceModel.leave_type.asc())
        )
        result = await self.session.execute(stmt)
        return [_leave_balance_from_orm(model) for model in result.scalars().all()]

    async def upsert_balance(self, balance: ent.LeaveBalance) -> ent.LeaveBalance:
        stmt = (
            pg_insert(LeaveBalanceModel)
            .values(
                tenant_id=balance.tenant_id,
                employee_id=balance.employee_id,
                leave_type=balance.leave_type,
                balance=balance.balance,
                id=balance.id if balance.id is not None else uuid.uuid4(),
            )
            .on_conflict_do_update(
                index_elements=[
                    LeaveBalanceModel.tenant_id,
                    LeaveBalanceModel.employee_id,
                    LeaveBalanceModel.leave_type,
                ],
                set_={
                    "balance": balance.balance,
                    "updated_at": func.now(),
                },
            )
            .returning(LeaveBalanceModel)
        )
        model = (await self.session.execute(stmt)).scalar_one()
        return _leave_balance_from_orm(model)

    # ------------------------------------------------------------------
    # Leave requests
    # ------------------------------------------------------------------

    async def create_leave_request(self, request: ent.LeaveRequest) -> ent.LeaveRequest:
        model = _leave_request_to_orm(request)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _leave_request_from_orm(model)

    async def get_leave_request(
        self, request_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ent.LeaveRequest | None:
        stmt = select(LeaveRequestModel).where(
            LeaveRequestModel.tenant_id == tenant_id,
            LeaveRequestModel.id == request_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _leave_request_from_orm(model) if model is not None else None

    async def update_leave_request(self, request: ent.LeaveRequest) -> ent.LeaveRequest:
        if request.id is None:
            raise ValueError("leave request is missing an id")
        stmt = (
            update(LeaveRequestModel)
            .where(
                LeaveRequestModel.tenant_id == request.tenant_id,
                LeaveRequestModel.id == request.id,
            )
            .values(
                employee_id=request.employee_id,
                leave_type=request.leave_type,
                start_date=request.start_date,
                end_date=request.end_date,
                days=request.days,
                status=LeaveRequestStatusModel(request.status.value),
                reason=request.reason,
                approved_by=request.approved_by,
                approved_at=request.approved_at,
                updated_at=func.now(),
            )
            .returning(LeaveRequestModel)
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise ValueError(f"leave request {request.id} not found")
        return _leave_request_from_orm(model)

    async def transition_leave_status(
        self,
        request_id: uuid.UUID,
        from_status: str,
        to_status: str,
        *,
        tenant_id: uuid.UUID,
        approved_by: uuid.UUID | None = None,
        approved_at: object | None = None,
    ) -> ent.LeaveRequest | None:
        """Atomic conditional transition (CAS) — ``None`` if not in ``from_status``.

        Guards the balance-relevant approve/cancel flows so a concurrent
        duplicate request can never flip the row twice (docs §4.3, §4.5).
        """
        values: dict[str, object] = {
            "status": LeaveRequestStatusModel(to_status),
            "updated_at": func.now(),
        }
        if approved_by is not None:
            values["approved_by"] = approved_by
        if approved_at is not None:
            values["approved_at"] = approved_at
        stmt = (
            update(LeaveRequestModel)
            .where(
                LeaveRequestModel.tenant_id == tenant_id,
                LeaveRequestModel.id == request_id,
                LeaveRequestModel.status == LeaveRequestStatusModel(from_status),
            )
            .values(**values)
            .returning(LeaveRequestModel)
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _leave_request_from_orm(model) if model is not None else None

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
    ) -> Sequence[ent.LeaveRequest]:
        stmt = select(LeaveRequestModel).where(LeaveRequestModel.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(LeaveRequestModel.status == status)
        if employee_id is not None:
            stmt = stmt.where(LeaveRequestModel.employee_id == employee_id)
        if from_date is not None:
            stmt = stmt.where(LeaveRequestModel.start_date >= from_date)
        if to_date is not None:
            stmt = stmt.where(LeaveRequestModel.end_date <= to_date)
        stmt = stmt.order_by(LeaveRequestModel.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return [_leave_request_from_orm(model) for model in result.scalars().all()]

    # ------------------------------------------------------------------
    # Compensation (recorded at hire; read-side owned by the payroll repo)
    # ------------------------------------------------------------------

    async def create_compensation(self, compensation: ent.Compensation) -> ent.Compensation:
        model = _compensation_to_orm(compensation)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _compensation_from_orm(model)

    async def get_compensation(
        self,
        employee_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        effective_for: date,
    ) -> ent.Compensation | None:
        """Latest active compensation effective at or before ``effective_for``.

        Mirror of the payroll repository read, kept here so the HR employee
        detail view can surface current compensation without the HR feature
        reaching into the payroll feature (docs §4.7, Rule 7 pick).
        """
        stmt = (
            select(CompensationModel)
            .where(
                CompensationModel.tenant_id == tenant_id,
                CompensationModel.employee_id == employee_id,
                CompensationModel.is_active.is_(True),
                CompensationModel.effective_from <= effective_for,
            )
            .order_by(CompensationModel.effective_from.desc())
            .limit(1)
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _compensation_from_orm(model) if model is not None else None

    # ------------------------------------------------------------------
    # LeaveLedgerPort (implemented for payroll — one sanctioned cross-feature read)
    # ------------------------------------------------------------------

    async def approved_unpaid_days(
        self,
        employee_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> int:
        """Count approved ``unpaid`` leave days overlapping the payroll period.

        Overlap is inclusive ``[max(start, period_start), min(end, period_end)]``
        and never negative (docs §4.9 Rule 9 proration input).
        """
        stmt = select(LeaveRequestModel).where(
            LeaveRequestModel.tenant_id == tenant_id,
            LeaveRequestModel.employee_id == employee_id,
            LeaveRequestModel.leave_type == _UNPAID_LEAVE,
            LeaveRequestModel.status == LeaveRequestStatusModel.APPROVED,
            LeaveRequestModel.start_date <= period_end,
            LeaveRequestModel.end_date >= period_start,
        )
        models = (await self.session.execute(stmt)).scalars().all()
        total = 0
        for model in models:
            overlap_start = max(model.start_date, period_start)
            overlap_end = min(model.end_date, period_end)
            total += max((overlap_end - overlap_start).days + 1, 0)
        return total

    async def _find_movement_by_ref(
        self,
        employee_id: uuid.UUID,
        leave_type: str,
        ref_type: str,
        ref_id: str | None,
        tenant_id: uuid.UUID,
    ) -> ent.LeaveMovement | None:
        stmt = select(LeaveMovementModel).where(
            LeaveMovementModel.tenant_id == tenant_id,
            LeaveMovementModel.employee_id == employee_id,
            LeaveMovementModel.leave_type == leave_type,
            LeaveMovementModel.ref_type == ref_type,
            LeaveMovementModel.ref_id == ref_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _leave_movement_from_orm(model) if model is not None else None
