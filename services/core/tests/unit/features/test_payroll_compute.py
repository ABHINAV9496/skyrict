"""PayrollCompute unit tests — rules 7/9 math, pure, DB-free.

Covers proration (Rule 9), statutory deductions, rounding modes, and totals.
The effective-date pick (Rule 7) is repository-side and tested in the service
suite via the fake's ``get_compensation``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from core.core.constants import PayrollRounding
from core.domain import entities as ent
from core.domain.value_objects import Money
from core.features.payroll.service import PayrollCompute

pytestmark = pytest.mark.unit

USD = "USD"


def _money(amount: str) -> Money:
    return Money(Decimal(amount), USD)


class TestPayDaysRule9:
    def test_full_period_no_reductions(self) -> None:
        assert PayrollCompute.pay_days(period_start=date(2024, 5, 1), period_end=date(2024, 5, 31)) == 31

    def test_hire_mid_period_prorates_from_hire(self) -> None:
        assert (
            PayrollCompute.pay_days(
                period_start=date(2024, 5, 1),
                period_end=date(2024, 5, 31),
                hire_date=date(2024, 5, 10),
            )
            == 22  # May 10..31 inclusive
        )

    def test_termination_mid_period_prorates_to_termination(self) -> None:
        assert (
            PayrollCompute.pay_days(
                period_start=date(2024, 5, 1),
                period_end=date(2024, 5, 31),
                termination_date=date(2024, 5, 15),
            )
            == 15  # May 1..15 inclusive
        )

    def test_unpaid_leave_overlap_reduces_pay_days(self) -> None:
        assert (
            PayrollCompute.pay_days(
                period_start=date(2024, 5, 1),
                period_end=date(2024, 5, 31),
                unpaid_days=5,
            )
            == 26
        )

    def test_unpaid_overlap_never_negative(self) -> None:
        assert (
            PayrollCompute.pay_days(
                period_start=date(2024, 5, 1),
                period_end=date(2024, 5, 10),
                unpaid_days=99,
            )
            == 0
        )

    def test_pay_days_never_negative_with_all_reductions(self) -> None:
        assert (
            PayrollCompute.pay_days(
                period_start=date(2024, 5, 1),
                period_end=date(2024, 5, 10),
                hire_date=date(2024, 5, 8),
                termination_date=date(2024, 5, 9),
                unpaid_days=3,
            )
            == 0
        )

    def test_hire_before_and_termination_after_period_are_noops(self) -> None:
        assert (
            PayrollCompute.pay_days(
                period_start=date(2024, 5, 1),
                period_end=date(2024, 5, 31),
                hire_date=date(2023, 1, 1),
                termination_date=date(2024, 12, 31),
            )
            == 31
        )


class TestComputeEntry:
    def test_full_salary_with_zero_rates(self) -> None:
        gross, deductions, net = PayrollCompute.compute_entry(
            base_salary=_money("3000"),
            pay_days=30,
            days_in_period=30,
            pf_rate=Decimal("0"),
            tax_rate=Decimal("0"),
            rounding=PayrollRounding.NEAREST,
        )
        assert gross.amount == Decimal("3000")
        assert deductions.amount == Decimal("0")
        assert net.amount == Decimal("3000")

    def test_statutory_deductions_are_percentages(self) -> None:
        gross, deductions, net = PayrollCompute.compute_entry(
            base_salary=_money("1000"),
            pay_days=30,
            days_in_period=30,
            pf_rate=Decimal("0.05"),  # 5%
            tax_rate=Decimal("0.10"),  # 10%
            rounding=PayrollRounding.NEAREST,
        )
        assert gross.amount == Decimal("1000")
        assert deductions.amount == Decimal("150")  # 50 pf + 100 tax
        assert net.amount == Decimal("850")

    def test_adjustment_is_flat_amount(self) -> None:
        _, deductions, net = PayrollCompute.compute_entry(
            base_salary=_money("1000"),
            pay_days=30,
            days_in_period=30,
            pf_rate=Decimal("0"),
            tax_rate=Decimal("0"),
            rounding=PayrollRounding.NEAREST,
            adjustments={"amount": "50"},
        )
        assert deductions.amount == Decimal("50")
        assert net.amount == Decimal("950")

    def test_prorated_gross_rounds_to_cents(self) -> None:
        gross, _, net = PayrollCompute.compute_entry(
            base_salary=_money("1000"),
            pay_days=15,
            days_in_period=30,
            pf_rate=Decimal("0"),
            tax_rate=Decimal("0"),
            rounding=PayrollRounding.NEAREST,
        )
        assert gross.amount == Decimal("500.00")
        assert net.amount == Decimal("500.00")

    @pytest.mark.parametrize(
        ("rounding", "expected"),
        [
            (PayrollRounding.NEAREST, Decimal("333.33")),
            (PayrollRounding.UP, Decimal("333.34")),
            (PayrollRounding.DOWN, Decimal("333.33")),
        ],
    )
    def test_rounding_modes(self, rounding, expected) -> None:
        gross, _, _ = PayrollCompute.compute_entry(
            base_salary=_money("1000"),
            pay_days=10,
            days_in_period=30,
            pf_rate=Decimal("0"),
            tax_rate=Decimal("0"),
            rounding=rounding,
        )
        assert gross.amount == expected

    def test_days_in_period_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="days_in_period"):
            PayrollCompute.compute_entry(
                base_salary=_money("1000"),
                pay_days=0,
                days_in_period=0,
                pf_rate=Decimal("0"),
                tax_rate=Decimal("0"),
                rounding=PayrollRounding.NEAREST,
            )


class TestComputeTotals:
    _tenant = uuid.uuid4()
    _run = uuid.uuid4()
    _employee = uuid.uuid4()

    def _entry(self, gross: str, net: str) -> ent.PayrollEntry:
        return ent.PayrollEntry(
            tenant_id=self._tenant,
            run_id=self._run,
            employee_id=self._employee,
            base_salary=_money("0"),
            pay_days=30,
            gross=_money(gross),
            deductions=_money("0"),
            net=_money(net),
        )

    def test_totals_sum_across_entries(self) -> None:
        entries = [self._entry("1000", "800"), self._entry("2000", "1700")]
        total_gross, total_net = PayrollCompute.compute_totals(entries)
        assert total_gross.amount == Decimal("3000")
        assert total_net.amount == Decimal("2500")

    def test_totals_require_same_currency(self) -> None:
        other = ent.PayrollEntry(
            tenant_id=self._tenant,
            run_id=self._run,
            employee_id=self._employee,
            base_salary=_money("0"),
            pay_days=30,
            gross=Money(Decimal("100"), "EUR"),
            deductions=Money(Decimal("0"), "EUR"),
            net=Money(Decimal("100"), "EUR"),
        )
        from skyrict_common.exceptions import ValidationError

        with pytest.raises(ValidationError, match="currenc"):
            PayrollCompute.compute_totals([self._entry("1000", "800"), other])

    def test_empty_run_raises(self) -> None:
        with pytest.raises(ValueError, match="empty run"):
            PayrollCompute.compute_totals([])
