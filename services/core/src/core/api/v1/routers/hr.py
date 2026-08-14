"""HR API endpoints — departments, employees, leave (HR-BE-002 §2, §7).

Every handler requires a valid access token bound to the routed tenant
(``get_current_user``) and resolves the tenant id from the request context.
Service ``ValueError`` results are translated to RFC 7807 domain errors via
:func:`raise_from_service_error`.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, Query

from core.api.deps import (
    get_current_user,
    get_department_service,
    get_employee_service,
    get_leave_service,
    get_tenant_id,
)
from core.api.v1.routers.errors import raise_from_service_error
from core.api.v1.schemas import (
    CompensationOut,
    DepartmentCreate,
    DepartmentOut,
    DepartmentUpdate,
    EmployeeCreate,
    EmployeeOut,
    EmployeeStatusBody,
    EmployeeUpdate,
    LeaveAccrueRequest,
    LeaveBalanceAdjustRequest,
    LeaveBalanceOut,
    LeaveMovementOut,
    LeaveRequestCreate,
    LeaveRequestOut,
    LeaveRequestRejectBody,
    TerminateRequest,
)
from core.core.constants import EmploymentStatus
from core.domain import entities as ent
from core.domain.value_objects import Money
from core.features.hr.service import DepartmentService, EmployeeService, LeaveService
from skyrict_common.exceptions import NotFoundError
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/hr", tags=["hr"])


async def _employee_out(
    employee: ent.Employee,
    employee_svc: EmployeeService,
    tenant_id: uuid.UUID,
) -> EmployeeOut:
    """Build an ``EmployeeOut`` including the current active compensation."""
    assert employee.id is not None
    out = EmployeeOut.model_validate(employee)
    compensation = await employee_svc.get_active_compensation(employee.id, tenant_id=tenant_id)
    out.active_compensation = (
        CompensationOut.from_entity(compensation) if compensation is not None else None
    )
    return out


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------


@router.get("/departments", response_model=ResponseEnvelope[list[DepartmentOut]])
async def list_departments(
    include_inactive: bool = Query(default=False),
    current_user: dict[str, Any] = Depends(get_current_user),
    department_svc: DepartmentService = Depends(get_department_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[list[DepartmentOut]]:
    departments = await department_svc.list(tenant_id, include_inactive=include_inactive)
    return ResponseEnvelope(data=[DepartmentOut.model_validate(d) for d in departments])


@router.post("/departments", response_model=ResponseEnvelope[DepartmentOut], status_code=201)
async def create_department(
    body: DepartmentCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
    department_svc: DepartmentService = Depends(get_department_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[DepartmentOut]:
    try:
        department = await department_svc.create(
            name=body.name,
            tenant_id=tenant_id,
            manager_employee_id=body.manager_employee_id,
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(
        data=DepartmentOut.model_validate(department), message="Department created"
    )


@router.patch("/departments/{department_id}", response_model=ResponseEnvelope[DepartmentOut])
async def update_department(
    department_id: uuid.UUID,
    body: DepartmentUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
    department_svc: DepartmentService = Depends(get_department_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[DepartmentOut]:
    department = await department_svc.get(department_id, tenant_id=tenant_id)
    if department is None:
        raise NotFoundError(f"department {department_id} not found")
    changes = body.model_dump(exclude_unset=True)
    updated = dataclasses.replace(department, **changes)
    result = await department_svc.update(updated, actor_user_id=current_user["user_id"])
    return ResponseEnvelope(data=DepartmentOut.model_validate(result), message="Department updated")


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------


@router.get("/employees", response_model=ResponseEnvelope[list[EmployeeOut]])
async def list_employees(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    department_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict[str, Any] = Depends(get_current_user),
    employee_svc: EmployeeService = Depends(get_employee_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[list[EmployeeOut]]:
    employees = await employee_svc.list(
        tenant_id,
        status=status,
        department_id=department_id,
        q=q,
        limit=limit,
        offset=offset,
    )
    return ResponseEnvelope(data=[EmployeeOut.model_validate(e) for e in employees])


@router.post("/employees", response_model=ResponseEnvelope[EmployeeOut], status_code=201)
async def create_employee(
    body: EmployeeCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
    employee_svc: EmployeeService = Depends(get_employee_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[EmployeeOut]:
    monthly_salary = None
    if body.monthly_salary is not None:
        monthly_salary = Money(Decimal(body.monthly_salary), body.currency)
    try:
        employee = await employee_svc.hire(
            tenant_id=tenant_id,
            first_name=body.first_name,
            last_name=body.last_name,
            email=body.email,
            phone=body.phone,
            job_title=body.job_title,
            hire_date=body.hire_date,
            department_id=body.department_id,
            user_id=body.user_id,
            monthly_salary=monthly_salary,
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(data=EmployeeOut.model_validate(employee), message="Employee hired")


@router.get("/employees/{employee_id}", response_model=ResponseEnvelope[EmployeeOut])
async def get_employee(
    employee_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(get_current_user),
    employee_svc: EmployeeService = Depends(get_employee_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[EmployeeOut]:
    employee = await employee_svc.get(employee_id, tenant_id=tenant_id)
    if employee is None:
        raise NotFoundError(f"employee {employee_id} not found")
    return ResponseEnvelope(data=await _employee_out(employee, employee_svc, tenant_id))


@router.patch("/employees/{employee_id}", response_model=ResponseEnvelope[EmployeeOut])
async def update_employee(
    employee_id: uuid.UUID,
    body: EmployeeUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
    employee_svc: EmployeeService = Depends(get_employee_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[EmployeeOut]:
    employee = await employee_svc.get(employee_id, tenant_id=tenant_id)
    if employee is None:
        raise NotFoundError(f"employee {employee_id} not found")
    changes = body.model_dump(exclude_unset=True)
    updated = dataclasses.replace(employee, **changes)
    try:
        result = await employee_svc.update(
            updated,
            changed_fields=list(changes.keys()),
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(data=EmployeeOut.model_validate(result), message="Employee updated")


@router.post("/employees/{employee_id}/status", response_model=ResponseEnvelope[EmployeeOut])
async def change_employee_status(
    employee_id: uuid.UUID,
    body: EmployeeStatusBody,
    current_user: dict[str, Any] = Depends(get_current_user),
    employee_svc: EmployeeService = Depends(get_employee_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[EmployeeOut]:
    try:
        employee = await employee_svc.change_status(
            employee_id=employee_id,
            tenant_id=tenant_id,
            new_status=EmploymentStatus(body.employment_status),
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(
        data=EmployeeOut.model_validate(employee), message="Employee status updated"
    )


@router.post("/employees/{employee_id}/terminate", response_model=ResponseEnvelope[EmployeeOut])
async def terminate_employee(
    employee_id: uuid.UUID,
    body: TerminateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    employee_svc: EmployeeService = Depends(get_employee_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[EmployeeOut]:
    termination_date = body.termination_date or date.today()
    try:
        employee = await employee_svc.terminate(
            employee_id=employee_id,
            tenant_id=tenant_id,
            termination_date=termination_date,
            reason=body.reason,
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(
        data=EmployeeOut.model_validate(employee), message="Employee terminated"
    )


# ---------------------------------------------------------------------------
# Leave requests
# ---------------------------------------------------------------------------


@router.get("/leave/requests", response_model=ResponseEnvelope[list[LeaveRequestOut]])
async def list_leave_requests(
    status: str | None = Query(default=None),
    employee_id: uuid.UUID | None = Query(default=None),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict[str, Any] = Depends(get_current_user),
    leave_svc: LeaveService = Depends(get_leave_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[list[LeaveRequestOut]]:
    requests = await leave_svc.list_leave_requests(
        tenant_id,
        status=status,
        employee_id=employee_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
    return ResponseEnvelope(data=[LeaveRequestOut.model_validate(r) for r in requests])


@router.post("/leave/requests", response_model=ResponseEnvelope[LeaveRequestOut], status_code=201)
async def create_leave_request(
    body: LeaveRequestCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
    leave_svc: LeaveService = Depends(get_leave_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[LeaveRequestOut]:
    try:
        request = await leave_svc.request(
            tenant_id=tenant_id,
            employee_id=body.employee_id,
            leave_type=body.leave_type,
            start_date=body.start_date,
            end_date=body.end_date,
            reason=body.reason,
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(
        data=LeaveRequestOut.model_validate(request), message="Leave request created"
    )


@router.get("/leave/requests/{request_id}", response_model=ResponseEnvelope[LeaveRequestOut])
async def get_leave_request(
    request_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(get_current_user),
    leave_svc: LeaveService = Depends(get_leave_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[LeaveRequestOut]:
    request = await leave_svc.get(request_id, tenant_id=tenant_id)
    if request is None:
        raise NotFoundError(f"leave request {request_id} not found")
    return ResponseEnvelope(data=LeaveRequestOut.model_validate(request))


@router.post(
    "/leave/requests/{request_id}/approve", response_model=ResponseEnvelope[LeaveRequestOut]
)
async def approve_leave_request(
    request_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(get_current_user),
    leave_svc: LeaveService = Depends(get_leave_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[LeaveRequestOut]:
    try:
        request, _balance = await leave_svc.approve(
            request_id=request_id,
            tenant_id=tenant_id,
            approved_by=current_user["user_id"],
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(
        data=LeaveRequestOut.model_validate(request), message="Leave request approved"
    )


@router.post(
    "/leave/requests/{request_id}/reject", response_model=ResponseEnvelope[LeaveRequestOut]
)
async def reject_leave_request(
    request_id: uuid.UUID,
    body: LeaveRequestRejectBody | None = Body(default=None),
    current_user: dict[str, Any] = Depends(get_current_user),
    leave_svc: LeaveService = Depends(get_leave_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[LeaveRequestOut]:
    reason = body.reason if body is not None else None
    try:
        request = await leave_svc.reject(
            request_id=request_id,
            tenant_id=tenant_id,
            reason=reason,
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(
        data=LeaveRequestOut.model_validate(request), message="Leave request rejected"
    )


@router.post(
    "/leave/requests/{request_id}/cancel", response_model=ResponseEnvelope[LeaveRequestOut]
)
async def cancel_leave_request(
    request_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(get_current_user),
    leave_svc: LeaveService = Depends(get_leave_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[LeaveRequestOut]:
    try:
        request, _balance = await leave_svc.cancel(
            request_id=request_id,
            tenant_id=tenant_id,
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(
        data=LeaveRequestOut.model_validate(request), message="Leave request cancelled"
    )


# ---------------------------------------------------------------------------
# Leave balances / movements / accrual
# ---------------------------------------------------------------------------


@router.get("/leave/balances", response_model=ResponseEnvelope[list[LeaveBalanceOut]])
async def list_leave_balances(
    employee_id: uuid.UUID = Query(...),
    current_user: dict[str, Any] = Depends(get_current_user),
    leave_svc: LeaveService = Depends(get_leave_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[list[LeaveBalanceOut]]:
    balances = await leave_svc.list_balances(employee_id, tenant_id=tenant_id)
    return ResponseEnvelope(data=[LeaveBalanceOut.model_validate(b) for b in balances])


@router.post("/leave/balances/adjust", response_model=ResponseEnvelope[LeaveBalanceOut])
async def adjust_leave_balance(
    body: LeaveBalanceAdjustRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    leave_svc: LeaveService = Depends(get_leave_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[LeaveBalanceOut]:
    try:
        new_balance = await leave_svc.adjust_balance(
            tenant_id=tenant_id,
            employee_id=body.employee_id,
            leave_type=body.leave_type,
            qty=body.qty,
            reason=body.reason,
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(
        data=LeaveBalanceOut(
            employee_id=body.employee_id,
            leave_type=body.leave_type,
            balance=new_balance,
        ),
        message="Leave balance adjusted",
    )


@router.post("/leave/accrue", response_model=ResponseEnvelope[LeaveMovementOut | None])
async def accrue_leave(
    body: LeaveAccrueRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    leave_svc: LeaveService = Depends(get_leave_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[LeaveMovementOut | None]:
    leave_year = body.leave_year or date.today().year
    try:
        movement = await leave_svc.accrue(
            tenant_id=tenant_id,
            employee_id=body.employee_id,
            leave_type=body.leave_type,
            year=leave_year,
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    if movement is None:
        return ResponseEnvelope(data=None, message="Leave already accrued for this period")
    return ResponseEnvelope(data=LeaveMovementOut.model_validate(movement), message="Leave accrued")


@router.get("/leave/movements", response_model=ResponseEnvelope[list[LeaveMovementOut]])
async def list_leave_movements(
    employee_id: uuid.UUID = Query(...),
    leave_type: str | None = Query(default=None),
    current_user: dict[str, Any] = Depends(get_current_user),
    leave_svc: LeaveService = Depends(get_leave_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[list[LeaveMovementOut]]:
    movements = await leave_svc.list_movements(
        employee_id, tenant_id=tenant_id, leave_type=leave_type
    )
    return ResponseEnvelope(data=[LeaveMovementOut.model_validate(m) for m in movements])
