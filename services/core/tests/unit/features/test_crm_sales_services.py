"""Pure-logic unit tests for the CRM & Sales feature services.

No database: these cover the module-level decision functions the services
delegate to - the opportunity pipeline transition rule (``_is_forward``), the
request->Money normalization helpers (``_normalize_amount_changes`` /
``_normalize_credit_limit_changes``), and the sales money math (``_totals`` /
``_quantize`` / ``_credit_check_passed``). The DB-backed behaviors are covered
by the integration API suite.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.domain.entities import Customer, SalesOrderLine
from core.domain.value_objects import Money, OpportunityStage
from core.features.crm.service import (
    _is_forward,
    _normalize_amount_changes,
    _normalize_credit_limit_changes,
)
from core.features.sales.service import _credit_check_passed, _quantize, _totals
from skyrict_common.exceptions import ValidationError

pytestmark = pytest.mark.unit


class TestOpportunityPipeline:
    def test_forward_one_step_only(self) -> None:
        assert _is_forward(OpportunityStage.QUALIFIED, OpportunityStage.PROSPECTING)
        assert _is_forward(OpportunityStage.PROPOSAL, OpportunityStage.QUALIFIED)
        assert _is_forward(OpportunityStage.NEGOTIATION, OpportunityStage.PROPOSAL)

    def test_cannot_skip_stages(self) -> None:
        assert not _is_forward(OpportunityStage.PROPOSAL, OpportunityStage.PROSPECTING)
        assert not _is_forward(OpportunityStage.NEGOTIATION, OpportunityStage.QUALIFIED)

    def test_terminals_win_from_any_non_terminal(self) -> None:
        assert _is_forward(OpportunityStage.WON, OpportunityStage.PROSPECTING)
        assert _is_forward(OpportunityStage.WON, OpportunityStage.QUALIFIED)
        assert _is_forward(OpportunityStage.WON, OpportunityStage.NEGOTIATION)
        assert _is_forward(OpportunityStage.LOST, OpportunityStage.PROPOSAL)

    def test_terminals_are_immutable(self) -> None:
        assert not _is_forward(OpportunityStage.PROPOSAL, OpportunityStage.WON)
        assert not _is_forward(OpportunityStage.WON, OpportunityStage.LOST)
        assert not _is_forward(OpportunityStage.LOST, OpportunityStage.WON)

    def test_stage_cannot_stay_put(self) -> None:
        assert not _is_forward(OpportunityStage.PROSPECTING, OpportunityStage.PROSPECTING)

    def test_initial_stage_cannot_reverse(self) -> None:
        assert not _is_forward(OpportunityStage.PROSPECTING, OpportunityStage.QUALIFIED)


class TestNormalizeAmountChanges:
    def test_bare_amount_defaults_to_usd(self) -> None:
        changes: dict[str, object] = {"amount": Decimal("1250.00")}
        _normalize_amount_changes(changes)
        assert changes["amount"] == Money(Decimal("1250.00"), "USD")
        assert "currency" not in changes

    def test_amount_with_currency(self) -> None:
        changes: dict[str, object] = {"amount": Decimal("1250.00"), "currency": "EUR"}
        _normalize_amount_changes(changes)
        assert changes["amount"] == Money(Decimal("1250.00"), "EUR")

    def test_explicit_none_clears_amount_and_currency(self) -> None:
        changes: dict[str, object] = {"amount": None, "currency": "EUR"}
        _normalize_amount_changes(changes)
        assert changes["amount"] is None
        assert "currency" not in changes

    def test_bare_currency_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _normalize_amount_changes({"currency": "EUR"})

    def test_bad_currency_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _normalize_amount_changes({"amount": Decimal("10"), "currency": "not-a-code"})

    def test_unrelated_changes_pass_through(self) -> None:
        changes: dict[str, object] = {"name": "New name"}
        _normalize_amount_changes(changes)
        assert changes == {"name": "New name"}


class TestNormalizeCreditLimitChanges:
    def test_bare_limit_defaults_to_usd(self) -> None:
        changes: dict[str, object] = {"credit_limit": Decimal("5000.00")}
        _normalize_credit_limit_changes(changes)
        assert changes["credit_limit"] == Money(Decimal("5000.00"), "USD")

    def test_limit_with_currency(self) -> None:
        changes: dict[str, object] = {"credit_limit": Decimal("5000.00"), "currency": "EUR"}
        _normalize_credit_limit_changes(changes)
        assert changes["credit_limit"] == Money(Decimal("5000.00"), "EUR")

    def test_explicit_none_clears_limit(self) -> None:
        changes: dict[str, object] = {"credit_limit": None, "currency": "EUR"}
        _normalize_credit_limit_changes(changes)
        assert changes["credit_limit"] is None
        assert "currency" not in changes

    def test_bare_currency_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _normalize_credit_limit_changes({"currency": "EUR"})


class TestSalesMoney:
    def test_quantize_two_decimal_places(self) -> None:
        assert _quantize(Decimal("10.006")) == Decimal("10.01")
        assert _quantize(Decimal("10.004")) == Decimal("10.00")
        # The quantum is Decimal("0.0001") storage precision; totals are 2dp.
        assert _quantize(Decimal("10.0050")) == Decimal("10.00")

    def test_totals_derive_from_lines(self) -> None:
        line = SalesOrderLine(
            tenant_id=__import__("uuid").uuid4(),
            order_id=__import__("uuid").uuid4(),
            product_id=__import__("uuid").uuid4(),
            product_name="Widget",
            sku="W-1",
            quantity=Decimal("3"),
            unit_price=Decimal("10.00"),
            discount=Decimal("0"),
            tax=Decimal("0"),
            line_total=Decimal("30.00"),
        )
        assert _totals([line]) == (
            Decimal("30.00"),
            Decimal("0.00"),
            Decimal("0.00"),
            Decimal("30.00"),
        )

    def test_totals_include_tax_and_discount(self) -> None:
        subtotal = Decimal("100.00")
        discount = Decimal("10.00")
        tax = Decimal("9.00")
        assert _quantize(subtotal - discount + tax) == Decimal("99.00")


class TestCreditCheck:
    def _customer(self, limit: Money | None) -> Customer:
        return Customer(
            tenant_id=__import__("uuid").uuid4(),
            customer_code="C-1",
            name="Acme",
            credit_limit=limit,
        )

    def test_no_limit_passes(self) -> None:
        assert _credit_check_passed(self._customer(None), Money(Decimal("1e9"), "USD"))

    def test_within_limit_passes(self) -> None:
        assert _credit_check_passed(
            self._customer(Money(Decimal("5000.00"), "USD")),
            Money(Decimal("4999.99"), "USD"),
        )

    def test_equal_to_limit_passes(self) -> None:
        assert _credit_check_passed(
            self._customer(Money(Decimal("5000.00"), "USD")),
            Money(Decimal("5000.00"), "USD"),
        )

    def test_over_limit_fails(self) -> None:
        assert not _credit_check_passed(
            self._customer(Money(Decimal("5000.00"), "USD")),
            Money(Decimal("5000.01"), "USD"),
        )
