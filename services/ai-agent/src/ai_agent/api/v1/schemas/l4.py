"""Pydantic schemas for the L4 what-if planning API (SKY-93, Commit 2).

Money is serialized as strings (L3 narrator convention) - the Decimal engine
output never touches a float on the wire.  The action discriminated union
covers the four engine action types; ``NewHireIn.employee`` carries the full
employee payload so the engine can add a roster member without an extra
round-trip to core.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# ---------- money helpers ----------


def _money(v: object) -> str:
    """Serialize a Decimal-or-string as a fixed two-decimal string."""
    from decimal import Decimal

    d = Decimal(str(v)) if not isinstance(v, Decimal) else v
    return f"{d.quantize(Decimal('0.01')):.2f}"


# ---------- action wire format (discriminated union) ----------


class SalaryMeritIn(BaseModel):
    type: Literal["salary_merit"] = "salary_merit"
    percent: str = Field(..., description="Increase fraction, e.g. 0.05 for 5%.")
    effective_month: int = Field(..., ge=1, le=36)


class NewHireEmployeeIn(BaseModel):
    employee_number: str | None = None
    first_name: str
    last_name: str
    department_id: uuid.UUID | None = None
    department_name: str | None = None
    job_title: str
    hire_date: date
    monthly_salary: str
    currency: str
    monthly_benefit_cost: str


class NewHireIn(BaseModel):
    type: Literal["new_hire"] = "new_hire"
    employee: NewHireEmployeeIn
    effective_month: int = Field(..., ge=1, le=36)


class ReductionIn(BaseModel):
    type: Literal["reduction"] = "reduction"
    employee_id: str = Field(..., description="Employee ID (UUID string).")
    effective_month: int = Field(..., ge=1, le=36)


class BenefitChangeIn(BaseModel):
    type: Literal["benefit_change"] = "benefit_change"
    employee_id: str = Field(..., description="Employee ID (UUID string).")
    monthly_benefit_cost: str
    effective_month: int = Field(..., ge=1, le=36)


ScenarioActionIn = Annotated[
    SalaryMeritIn | NewHireIn | ReductionIn | BenefitChangeIn,
    Field(discriminator="type"),
]


# ---------- projection output ----------


class ProjectionMonthOut(BaseModel):
    month: int
    headcount: int
    salary_cost: str
    benefit_cost: str
    total_cost: str


class ProjectionOut(BaseModel):
    currency: str
    horizon: int
    months: list[ProjectionMonthOut]
    salary_total: str
    benefit_total: str
    grand_total: str


# ---------- scenario create ----------


class ScenarioCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    base_as_of: date
    horizon: int = Field(default=12, ge=1, le=36)
    actions: list[ScenarioActionIn] = Field(default_factory=list)


# ---------- scenario detail ----------


class ScenarioOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    base_as_of: date
    horizon: int
    currency: str
    actions: list[dict[str, object]]
    projection: ProjectionOut
    created_by: uuid.UUID
    created_at: date


class ScenarioListItemOut(BaseModel):
    id: uuid.UUID
    name: str
    base_as_of: date
    horizon: int
    created_at: date


# ---------- compare ----------


class ScenarioCompareItemOut(BaseModel):
    id: uuid.UUID
    name: str
    base_as_of: date
    horizon: int
    projection: ProjectionOut


__all__ = [
    "BenefitChangeIn",
    "NewHireEmployeeIn",
    "NewHireIn",
    "ProjectionMonthOut",
    "ProjectionOut",
    "ReductionIn",
    "SalaryMeritIn",
    "ScenarioActionIn",
    "ScenarioCompareItemOut",
    "ScenarioCreateIn",
    "ScenarioListItemOut",
    "ScenarioOut",
]
