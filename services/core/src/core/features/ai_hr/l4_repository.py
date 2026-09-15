"""Payroll-base repository for the HR-AI-004 planning slice (Commit 1).

Serves the *source snapshot* the ai-agent what-if engine projects over: every
active roster employee's current salary (latest effective ``erp_compensation``
row as of a date), their enrolled benefit cost (latest ``enrolled`` election
per plan, joined to the plan's ``monthly_cost_cents``), and their department.
No scenario logic lives here - this is pure read-only projection from existing
HR/payroll tables, so the engine in ai-agent stays a pure Decimal computation.

Money is carried as ``Decimal`` here and serialized as strings by the schema
layer (L3 narrator convention) so cents never round-trip through a float.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.features.hr.models.department import DepartmentModel
from core.features.hr.models.employee import EmployeeModel, EmploymentStatus
from core.features.payroll.models.benefits import (
    BENEFIT_ELECTION_ENROLLED,
    BenefitElectionModel,
    BenefitPlanModel,
)
from core.features.payroll.models.compensation import CompensationModel

_ACTIVE = (EmploymentStatus.ACTIVE, EmploymentStatus.ON_LEAVE)
_CURRENCY_FALLBACK = "USD"
_CENTS_TO_DECIMAL = Decimal("100")
_CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class PayrollBaseEmployee:
    """One roster employee in the planning base snapshot."""

    employee_id: uuid.UUID
    employee_number: str
    first_name: str
    last_name: str
    department_id: uuid.UUID | None
    department_name: str | None
    job_title: str
    employment_status: str
    hire_date: date
    monthly_salary: Decimal
    currency: str
    monthly_benefit_cost: Decimal


@dataclass(frozen=True, slots=True)
class PayrollBase:
    """The whole planning base: per-employee rows plus org aggregates."""

    tenant_id: uuid.UUID
    as_of: date
    currency: str
    employees: tuple[PayrollBaseEmployee, ...]

    @property
    def headcount(self) -> int:
        return len(self.employees)

    @property
    def monthly_salary_total(self) -> Decimal:
        return sum((e.monthly_salary for e in self.employees), start=Decimal("0"))

    @property
    def monthly_benefit_cost_total(self) -> Decimal:
        return sum((e.monthly_benefit_cost for e in self.employees), start=Decimal("0"))


class PayrollBaseRepository:
    """Read-only queries over the ERP HR/payroll tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_payroll_base(self, tenant_id: uuid.UUID, *, as_of: date) -> PayrollBase:
        employees = await self._active_employees(tenant_id)
        salaries = await self._current_salaries(tenant_id, as_of)
        benefits = await self._benefit_costs(tenant_id)

        currency = next(iter(salaries.values()))[1] if salaries else _CURRENCY_FALLBACK
        rows: list[PayrollBaseEmployee] = []
        for emp, department_name in employees:
            salary, emp_currency = salaries.get(emp.id, (Decimal("0"), currency))
            rows.append(
                PayrollBaseEmployee(
                    employee_id=emp.id,
                    employee_number=emp.employee_number,
                    first_name=emp.first_name,
                    last_name=emp.last_name,
                    department_id=emp.department_id,
                    department_name=department_name,
                    job_title=emp.job_title,
                    employment_status=emp.employment_status.value,
                    hire_date=emp.hire_date,
                    monthly_salary=salary,
                    currency=emp_currency,
                    monthly_benefit_cost=benefits.get(emp.id, Decimal("0")),
                )
            )

        return PayrollBase(
            tenant_id=tenant_id,
            as_of=as_of,
            currency=currency,
            employees=tuple(rows),
        )

    async def _active_employees(
        self, tenant_id: uuid.UUID
    ) -> list[tuple[EmployeeModel, str | None]]:
        stmt = (
            select(EmployeeModel, DepartmentModel.name)
            .outerjoin(
                DepartmentModel,
                and_(
                    DepartmentModel.tenant_id == EmployeeModel.tenant_id,
                    DepartmentModel.id == EmployeeModel.department_id,
                ),
            )
            .where(
                EmployeeModel.tenant_id == tenant_id,
                EmployeeModel.employment_status.in_(_ACTIVE),
            )
            .order_by(EmployeeModel.hire_date, EmployeeModel.id)
        )
        return [(emp, dept_name) for emp, dept_name in (await self._session.execute(stmt)).all()]

    async def _current_salaries(
        self, tenant_id: uuid.UUID, as_of: date
    ) -> dict[uuid.UUID, tuple[Decimal, str]]:
        rn = (
            func.row_number()
            .over(
                partition_by=(CompensationModel.tenant_id, CompensationModel.employee_id),
                order_by=(CompensationModel.effective_from.desc(), CompensationModel.id.desc()),
            )
            .label("rn")
        )
        latest = (
            select(
                CompensationModel.employee_id,
                CompensationModel.monthly_salary,
                CompensationModel.currency,
                rn,
            )
            .where(
                CompensationModel.tenant_id == tenant_id,
                CompensationModel.is_active.is_(True),
                CompensationModel.effective_from <= as_of,
            )
            .subquery()
        )
        stmt = (
            select(latest.c.employee_id, latest.c.monthly_salary, latest.c.currency)
            .where(latest.c.rn == 1)
            .order_by(latest.c.employee_id)
        )
        # ``erp_compensation.monthly_salary`` is NUMERIC(18,4); normalize to cents
        # at the source so every consumer (DTO money(), the ai-agent engine) sees
        # fixed-2dp Decimal regardless of the column's declared scale.
        return {
            row[0]: (Decimal(row[1]).quantize(_CENT), row[2])
            for row in (await self._session.execute(stmt)).all()
        }

    async def _benefit_costs(self, tenant_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
        rn = (
            func.row_number()
            .over(
                partition_by=(
                    BenefitElectionModel.tenant_id,
                    BenefitElectionModel.employee_id,
                    BenefitElectionModel.plan_id,
                ),
                order_by=(
                    BenefitElectionModel.effective_from.desc(),
                    BenefitElectionModel.id.desc(),
                ),
            )
            .label("ern")
        )
        latest = (
            select(BenefitElectionModel.employee_id, BenefitElectionModel.plan_id, rn)
            .where(
                BenefitElectionModel.tenant_id == tenant_id,
                BenefitElectionModel.status == BENEFIT_ELECTION_ENROLLED,
            )
            .subquery()
        )
        stmt = (
            select(latest.c.employee_id, func.sum(BenefitPlanModel.monthly_cost_cents))
            .join(
                BenefitPlanModel,
                and_(
                    BenefitPlanModel.tenant_id == tenant_id,
                    BenefitPlanModel.id == latest.c.plan_id,
                    BenefitPlanModel.is_active.is_(True),
                ),
            )
            .where(latest.c.ern == 1)
            .group_by(latest.c.employee_id)
        )
        result: dict[uuid.UUID, Decimal] = {}
        for employee_id, cents in (await self._session.execute(stmt)).all():
            if cents is None:
                continue
            result[employee_id] = (Decimal(cents) / _CENTS_TO_DECIMAL).quantize(_CENT)
        return result


__all__ = ["PayrollBase", "PayrollBaseEmployee", "PayrollBaseRepository"]
