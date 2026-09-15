"""Hand-check tests for the HR-AI-004 what-if engine (SKY-93, Commit 1).

The DoD's exact-money contract: 10 employees at 5000.00 with a 5% merit in
month 4 must project to *exactly* 50000.00 salary cost for months 1-3 and
52500.00 for months 4-12 - asserted as identical Decimals/strings, never
approx. All math lives in ``ai_agent.features.l4.engine``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ai_agent.features.l4.engine import (
    BenefitChange,
    NewHire,
    PayrollBase,
    PayrollEmployee,
    Reduction,
    SalaryMerit,
    project,
)

_AS_OF = date(2026, 1, 1)


def _emp(
    index: int,
    *,
    salary: str = "5000.00",
    benefit: str = "0.00",
    department: str | None = "Eng",
) -> PayrollEmployee:
    return PayrollEmployee(
        employee_id=f"emp-{index:02d}",
        first_name="Ada",
        last_name=f"L{index}",
        department_id="dept-1" if department else None,
        department_name=department,
        job_title="Engineer",
        hire_date=date(2024, 1, 1),
        monthly_salary=Decimal(salary),
        currency="USD",
        monthly_benefit_cost=Decimal(benefit),
    )


def _base(employees: tuple[PayrollEmployee, ...]) -> PayrollBase:
    return PayrollBase(as_of=_AS_OF, currency="USD", employees=employees)


def _salary_costs(result: object) -> list[str]:
    return [f"{m.salary_cost:.2f}" for m in result.months]


def test_handcheck_merit_month4_is_exact() -> None:
    """10 x 5000, 5% merit effective month 4 -> 50000.00 then 52500.00."""
    base = _base(tuple(_emp(i) for i in range(10)))
    result = project(base, [SalaryMerit(percent=Decimal("0.05"), effective_month=4)])

    assert result.currency == "USD"
    assert result.horizon == 12
    assert len(result.months) == 12
    # Headcount stays 10 all year.
    assert [m.headcount for m in result.months] == [10] * 12
    # The exact money contract - exact strings, no tolerance.
    assert _salary_costs(result) == ["50000.00"] * 3 + ["52500.00"] * 9
    assert f"{result.salary_total:.2f}" == "622500.00"
    assert f"{result.benefit_total:.2f}" == "0.00"
    assert f"{result.grand_total:.2f}" == "622500.00"


def test_handcheck_salary_total_matches_sum_of_months() -> None:
    """Totals are Decimal sums of the months, not float rounding artifacts."""
    base = _base(tuple(_emp(i) for i in range(10)))
    result = project(base, [SalaryMerit(percent=Decimal("0.05"), effective_month=4)])
    manual = sum((m.salary_cost for m in result.months), start=Decimal("0"))
    assert result.salary_total == manual


def test_no_actions_projects_flat_base() -> None:
    base = _base((_emp(0), _emp(1)))
    result = project(base, [])
    assert _salary_costs(result) == ["10000.00"] * 12
    assert result.months[0].headcount == 2
    assert result.months[11].total_cost == Decimal("10000.00")


def test_merit_quantity_is_exact_cents_half_up() -> None:
    # 5250 * 5% = 262.50 -> 5512.50; a third merit on an odd cent rounds HALF_UP.
    base = _base((_emp(0, salary="5250.00"),))
    result = project(base, [SalaryMerit(percent=Decimal("0.05"), effective_month=2)])
    assert f"{result.months[1].salary_cost:.2f}" == "5512.50"


def test_new_hire_joins_from_effective_month() -> None:
    base = _base((_emp(0),))
    hire = NewHire(employee=_emp(1), effective_month=4)
    result = project(base, [hire])
    assert result.months[0].headcount == 1
    assert result.months[3].headcount == 2
    assert _salary_costs(result) == ["5000.00"] * 3 + ["10000.00"] * 9


def test_reduction_stops_at_effective_month() -> None:
    base = _base((_emp(0), _emp(1)))
    result = project(base, [Reduction(employee_id="emp-01", effective_month=4)])
    assert result.months[0].headcount == 2
    assert result.months[3].headcount == 1
    assert _salary_costs(result) == ["10000.00"] * 3 + ["5000.00"] * 9


def test_benefit_change_lands_from_effective_month() -> None:
    base = _base((_emp(0, benefit="100.00"),))
    result = project(
        base,
        [
            BenefitChange(
                employee_id="emp-00", monthly_benefit_cost=Decimal("250.00"), effective_month=5
            )
        ],
    )
    assert f"{result.months[0].benefit_cost:.2f}" == "100.00"
    assert f"{result.months[4].benefit_cost:.2f}" == "250.00"
    # 4 months at 100.00 + 8 months at 250.00 = 400.00 + 2000.00.
    assert f"{result.benefit_total:.2f}" == "2400.00"


def test_out_of_range_effective_month_rejected() -> None:
    base = _base((_emp(0),))
    with pytest.raises(ValueError, match=r"outside 1\.\.12"):
        project(base, [SalaryMerit(percent=Decimal("0.05"), effective_month=13)])


def test_zero_horizon_rejected() -> None:
    with pytest.raises(ValueError, match="horizon must be >= 1"):
        project(_base(()), [], horizon=0)
