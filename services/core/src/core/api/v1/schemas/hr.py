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

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

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
    email: EmailStr = Field(..., max_length=320)
    phone: str = Field(..., min_length=1, max_length=50)
    user_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    monthly_salary: Decimal | None = Field(
        default=None, gt=0, description="initial gross monthly salary (optional)"
    )
    currency: str = Field(default="USD", min_length=3, max_length=3)

    @field_validator("first_name", "last_name", "email", "phone", mode="before")
    @classmethod
    def _strip_reject_blank(cls, value: object) -> object:
        """Trim surrounding whitespace; whitespace-only values are invalid."""
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("must not be blank")
            return stripped
        return value


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


class LeaveTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    is_accrual: bool


class PortalLeaveRequestCreate(BaseModel):
    """Self-service submit — ``employee_id`` is forced server-side."""

    leave_type: str = Field(..., min_length=1, max_length=50)
    start_date: date
    end_date: date
    reason: str | None = Field(default=None, max_length=500)


class PortalMeOut(BaseModel):
    """Everything the /leave portal needs on load: who I am + my leave state."""

    employee: EmployeeOut
    leave_types: list[LeaveTypeOut]
    balances: list[LeaveBalanceOut]


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


class AttendanceUpsertRequest(BaseModel):
    """Log or correct one day's attendance; ``pay_impact`` is derived server-side."""

    employee_id: uuid.UUID
    work_date: date
    status: Literal["on_time", "late", "absent"]
    note: str | None = Field(default=None, max_length=500)


class AttendanceRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    work_date: date
    status: str
    pay_impact: str
    note: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Joined display fields (module-wide list); None on single-employee reads.
    first_name: str | None = None
    last_name: str | None = None
    employee_number: str | None = None


__all__ = [
    "AttendanceRecordOut",
    "AttendanceUpsertRequest",
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
    "LeaveTypeOut",
    "PortalLeaveRequestCreate",
    "PortalMeOut",
    "TerminateRequest",
]
