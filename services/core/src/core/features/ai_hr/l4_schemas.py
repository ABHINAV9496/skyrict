"""Response schemas for the HR-AI-004 payroll-base endpoint (Commit 1).

Money is serialized as strings - the L3 narrator convention - so the Decimal
amounts projected by the ai-agent engine never lose precision to a float
round-trip. Totals are computed in Decimal by the repository's dataclass
(``PayrollBase``), so a hand-check like 10 x 5000 with a 5% merit lands on the
exact cents: ``"50000.00"`` / ``"52500.00"``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from core.features.ai_hr.l4_repository import PayrollBase, PayrollBaseEmployee

_MONEY_PLACES = Decimal("0.01")


def money(value: Decimal) -> str:
    """Serialize a Decimal as a fixed two-decimal string (e.g. ``"50000.00"``)."""
    return f"{value.quantize(_MONEY_PLACES):.2f}"


class PayrollBaseEmployeeOut(BaseModel):
    """One roster employee's planning snapshot."""

    employee_id: uuid.UUID
    employee_number: str
    first_name: str
    last_name: str
    department_id: uuid.UUID | None
    department_name: str | None
    job_title: str
    employment_status: str
    hire_date: date
    monthly_salary: str
    currency: str
    monthly_benefit_cost: str


class PayrollBaseOut(BaseModel):
    """The full planning base the what-if engine projects over."""

    tenant_id: uuid.UUID
    as_of: date
    currency: str
    headcount: int
    monthly_salary_total: str
    monthly_benefit_cost_total: str
    employees: list[PayrollBaseEmployeeOut]


def employee_to_out(row: PayrollBaseEmployee) -> PayrollBaseEmployeeOut:
    return PayrollBaseEmployeeOut(
        employee_id=row.employee_id,
        employee_number=row.employee_number,
        first_name=row.first_name,
        last_name=row.last_name,
        department_id=row.department_id,
        department_name=row.department_name,
        job_title=row.job_title,
        employment_status=row.employment_status,
        hire_date=row.hire_date,
        monthly_salary=money(row.monthly_salary),
        currency=row.currency,
        monthly_benefit_cost=money(row.monthly_benefit_cost),
    )


def payroll_base_to_out(base: PayrollBase) -> PayrollBaseOut:
    return PayrollBaseOut(
        tenant_id=base.tenant_id,
        as_of=base.as_of,
        currency=base.currency,
        headcount=base.headcount,
        monthly_salary_total=money(base.monthly_salary_total),
        monthly_benefit_cost_total=money(base.monthly_benefit_cost_total),
        employees=[employee_to_out(row) for row in base.employees],
    )


__all__ = [
    "PayrollBaseEmployeeOut",
    "PayrollBaseOut",
    "payroll_base_to_out",
]
