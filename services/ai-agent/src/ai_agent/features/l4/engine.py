"""HR-AI-004 what-if projection engine (SKY-93, Commit 1).

Pure ``Decimal`` math over a payroll-base snapshot - no I/O, no LLM, no
database. The engine projects each roster employee's salary and benefit cost
forward over a horizon (default 12 months), applying adjustment *actions* at
their effective month:

- ``SalaryMerit``: an org-wide salary increase (percent) from month M onward.
- ``NewHire``: add a roster employee from month M onward.
- ``Reduction``: stop paying an employee from month M onward.
- ``BenefitChange``: set an employee's monthly benefit cost from month M onward.

All money stays ``Decimal`` end to end; the only quantize is to cents with
HALF_UP at the moment a merit lands, so a hand-check like 10 x 5000 with a 5%
merit in month 4 reproduces *exactly*: months 1-3 salary cost 50000.00, months
4+ 52500.00. The scenario-name/versioning, share/compare, and the finance
budget-draft bridge live in later commits; this module is the pure core.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

_HORIZON_DEFAULT = 12
_CENT = Decimal("0.01")
_PLUS_ONE = Decimal("1")


@dataclass(frozen=True, slots=True)
class PayrollEmployee:
    """A roster employee in the planning base (mirrors core's shape)."""

    employee_id: str
    first_name: str
    last_name: str
    department_id: str | None
    department_name: str | None
    job_title: str
    hire_date: date
    monthly_salary: Decimal
    currency: str
    monthly_benefit_cost: Decimal


@dataclass(frozen=True, slots=True)
class PayrollBase:
    """The planning base the engine projects over."""

    as_of: date
    currency: str
    employees: tuple[PayrollEmployee, ...]


@dataclass(frozen=True, slots=True)
class SalaryMerit:
    """Org-wide salary increase, applied from ``effective_month`` onward."""

    percent: Decimal
    effective_month: int


@dataclass(frozen=True, slots=True)
class NewHire:
    """Add a roster employee from ``effective_month`` onward."""

    employee: PayrollEmployee
    effective_month: int


@dataclass(frozen=True, slots=True)
class Reduction:
    """Stop paying an employee from ``effective_month`` onward."""

    employee_id: str
    effective_month: int


@dataclass(frozen=True, slots=True)
class BenefitChange:
    """Set an employee's monthly benefit cost from ``effective_month`` onward."""

    employee_id: str
    monthly_benefit_cost: Decimal
    effective_month: int


Action = SalaryMerit | NewHire | Reduction | BenefitChange


@dataclass(frozen=True, slots=True)
class ProjectionMonth:
    """One projected month's cost."""

    month: int
    headcount: int
    salary_cost: Decimal
    benefit_cost: Decimal
    total_cost: Decimal


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """The full 12-month projection plus org-wide totals."""

    currency: str
    horizon: int
    months: tuple[ProjectionMonth, ...]
    salary_total: Decimal
    benefit_total: Decimal
    grand_total: Decimal


@dataclass(slots=True)
class _EmployeeState:
    present: bool
    salary: Decimal
    benefit_cost: Decimal


def project(
    base: PayrollBase, actions: Sequence[Action], horizon: int = _HORIZON_DEFAULT
) -> ProjectionResult:
    """Project the base over ``horizon`` months applying ``actions``.

    Actions apply at the start of their ``effective_month`` and persist to the
    end of the horizon. Effective months must fall within 1..horizon.
    """
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1, got {horizon}")

    scheduled: dict[int, list[Action]] = defaultdict(list)
    for action in actions:
        if not 1 <= action.effective_month <= horizon:
            raise ValueError(f"effective_month {action.effective_month} outside 1..{horizon}")
        scheduled[action.effective_month].append(action)

    state: dict[str, _EmployeeState] = {
        emp.employee_id: _EmployeeState(
            present=True,
            salary=emp.monthly_salary,
            benefit_cost=emp.monthly_benefit_cost,
        )
        for emp in base.employees
    }

    months: list[ProjectionMonth] = []
    for month in range(1, horizon + 1):
        for action in scheduled.get(month, ()):
            _apply(state, action)
        present = [s for s in state.values() if s.present]
        salary_cost = sum((s.salary for s in present), start=Decimal("0"))
        benefit_cost = sum((s.benefit_cost for s in present), start=Decimal("0"))
        months.append(
            ProjectionMonth(
                month=month,
                headcount=len(present),
                salary_cost=salary_cost,
                benefit_cost=benefit_cost,
                total_cost=salary_cost + benefit_cost,
            )
        )

    return ProjectionResult(
        currency=base.currency,
        horizon=horizon,
        months=tuple(months),
        salary_total=sum((m.salary_cost for m in months), start=Decimal("0")),
        benefit_total=sum((m.benefit_cost for m in months), start=Decimal("0")),
        grand_total=sum((m.total_cost for m in months), start=Decimal("0")),
    )


def _apply(state: dict[str, _EmployeeState], action: Action) -> None:
    if isinstance(action, SalaryMerit):
        for entry in state.values():
            if entry.present:
                entry.salary = (entry.salary * (_PLUS_ONE + action.percent)).quantize(
                    _CENT, rounding=ROUND_HALF_UP
                )
    elif isinstance(action, NewHire):
        state[action.employee.employee_id] = _EmployeeState(
            present=True,
            salary=action.employee.monthly_salary,
            benefit_cost=action.employee.monthly_benefit_cost,
        )
    elif isinstance(action, Reduction):
        entry = state[action.employee_id]
        entry.present = False
    elif isinstance(action, BenefitChange):
        state[action.employee_id].benefit_cost = action.monthly_benefit_cost


__all__ = [
    "Action",
    "BenefitChange",
    "NewHire",
    "PayrollBase",
    "PayrollEmployee",
    "ProjectionMonth",
    "ProjectionResult",
    "Reduction",
    "SalaryMerit",
    "project",
]
