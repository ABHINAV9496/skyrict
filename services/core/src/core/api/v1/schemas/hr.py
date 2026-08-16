"""Pydantic request/response schemas for the HR API (HR-BE-002 §2, §7).

Entities map cleanly to these models (no ``Money`` fields), so the routers use
``model_validate`` against the pure-domain entities plus explicit builders
where an optional join (e.g. the employee's active compensation) applies.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.api.v1.schemas.payroll import MoneyOut


class DepartmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    manager_employee_id: uuid.UUID | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    manager_employee_id: uuid.UUID | None = None
    is_active: bool | None = None


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    manager_employee_id: uuid.UUID | None = None
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EmployeeCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    job_title: str = Field(..., min_length=1, max_length=200)
    hire_date: date
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    user_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    monthly_salary: Decimal | None = Field(
        default=None, gt=0, description="initial gross monthly salary (optional)"
    )
    currency: str = Field(default="USD", min_length=3, max_length=3)


class EmployeeUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    job_title: str | None = Field(default=None, min_length=1, max_length=200)
    hire_date: date | None = None
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    user_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None


class EmployeeStatusBody(BaseModel):
    employment_status: Literal["active", "on_leave"]


class TerminateRequest(BaseModel):
    termination_date: date | None = None
    reason: str | None = None


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_number: str
    first_name: str
    last_name: str
    job_title: str
    hire_date: date
    employment_status: str
    email: str | None = None
    phone: str | None = None
    user_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    termination_date: date | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    active_compensation: MoneyOut | None = None


class LeaveRequestCreate(BaseModel):
    employee_id: uuid.UUID
    leave_type: str = Field(..., min_length=1, max_length=50)
    start_date: date
    end_date: date
    reason: str | None = Field(default=None, max_length=500)


class LeaveRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    leave_type: str
    start_date: date
    end_date: date
    days: int
    status: str
    reason: str | None = None
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    created_at: datetime | None = None


class LeaveBalanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: uuid.UUID
    leave_type: str
    balance: int


class LeaveMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    leave_type: str
    qty: int
    ref_type: str
    ref_id: str | None = None
    reason: str | None = None
    occurred_at: datetime | None = None


class LeaveBalanceAdjustRequest(BaseModel):
    employee_id: uuid.UUID
    leave_type: str = Field(..., min_length=1, max_length=50)
    qty: int
    reason: str = Field(..., min_length=1, max_length=500)


class LeaveRequestRejectBody(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class LeaveAccrueRequest(BaseModel):
    employee_id: uuid.UUID
    leave_type: str = Field(default="annual", min_length=1, max_length=50)
    leave_year: int | None = None


__all__ = [
    "DepartmentCreate",
    "DepartmentOut",
    "DepartmentUpdate",
    "EmployeeCreate",
    "EmployeeOut",
    "EmployeeStatusBody",
    "EmployeeUpdate",
    "LeaveAccrueRequest",
    "LeaveBalanceAdjustRequest",
    "LeaveBalanceOut",
    "LeaveMovementOut",
    "LeaveRequestCreate",
    "LeaveRequestOut",
    "LeaveRequestRejectBody",
    "TerminateRequest",
]
