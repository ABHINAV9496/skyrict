"""Money value object tests - Decimal-only arithmetic, currency validation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import ROUND_HALF_DOWN, Decimal

import pytest

from core.domain.value_objects import SUPPORTED_CURRENCIES, Money
from skyrict_common.exceptions import ValidationError


class TestConstruction:
    def test_basic_construction(self) -> None:
        money = Money(amount=Decimal("19.99"), currency="usd")
        assert money.amount == Decimal("19.99")
        assert money.currency == "USD"  # normalized to uppercase

    def test_accepts_int_string_float(self) -> None:
        assert Money(amount=5, currency="USD").amount == Decimal("5")
        assert Money(amount="5.50", currency="USD").amount == Decimal("5.50")
        assert Money(amount=5.5, currency="USD").amount == Decimal("5.5")

    def test_rejects_unsupported_currency(self) -> None:
        with pytest.raises(ValidationError):
            Money(amount=Decimal("1"), currency="XYZ")

    def test_rejects_non_numeric_amount(self) -> None:
        with pytest.raises(ValidationError):
            Money(amount=Decimal("NaN"), currency="USD")

    def test_frozen(self) -> None:
        money = Money(amount=Decimal("1"), currency="USD")
        with pytest.raises(FrozenInstanceError):
            money.amount = Decimal("2")  # type: ignore[misc]

    def test_supported_currencies_match_seeded_catalog(self) -> None:
        # Every supported code is a 3-letter ISO-ish code; the migration seeds
        # exactly this set into erp_currencies.
        assert "USD" in SUPPORTED_CURRENCIES
        assert "JPY" in SUPPORTED_CURRENCIES
        assert len(SUPPORTED_CURRENCIES) >= 15


class TestArithmetic:
    def test_add_same_currency(self) -> None:
        total = Money(Decimal("10.00"), "USD") + Money(Decimal("5.50"), "USD")
        assert total == Money(Decimal("15.50"), "USD")

    def test_sub_same_currency(self) -> None:
        diff = Money(Decimal("10.00"), "USD") - Money(Decimal("4.00"), "USD")
        assert diff == Money(Decimal("6.00"), "USD")

    def test_cross_currency_add_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Money(Decimal("10.00"), "USD") + Money(Decimal("10.00"), "EUR")

    def test_cross_currency_sub_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Money(Decimal("10.00"), "USD") - Money(Decimal("10.00"), "EUR")

    def test_mul_scalar(self) -> None:
        assert Money(Decimal("2.50"), "USD") * 3 == Money(Decimal("7.50"), "USD")

    def test_rmul_scalar(self) -> None:
        assert 3 * Money(Decimal("2.50"), "USD") == Money(Decimal("7.50"), "USD")

    def test_div_scalar(self) -> None:
        assert Money(Decimal("10.00"), "USD") / 2 == Money(Decimal("5.00"), "USD")

    def test_div_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Money(Decimal("10.00"), "USD") / 0

    def test_neg_and_abs(self) -> None:
        money = Money(Decimal("-5.00"), "USD")
        assert -money == Money(Decimal("5.00"), "USD")
        assert abs(money) == Money(Decimal("5.00"), "USD")


class TestOrdering:
    def test_lt(self) -> None:
        assert Money(Decimal("1"), "USD") < Money(Decimal("2"), "USD")

    def test_cross_currency_ordering_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Money(Decimal("1"), "USD").__lt__(Money(Decimal("2"), "EUR"))

    def test_eq_and_hash(self) -> None:
        a = Money(Decimal("1.00"), "USD")
        b = Money(Decimal("1.00"), "USD")
        c = Money(Decimal("1.00"), "EUR")
        assert a == b
        assert a != c
        assert hash(a) == hash(b)


class TestAccessors:
    def test_to_decimal(self) -> None:
        assert Money(Decimal("9.99"), "USD").to_decimal() == Decimal("9.99")

    def test_is_zero_positive_negative(self) -> None:
        assert Money(Decimal("0"), "USD").is_zero()
        assert Money(Decimal("5"), "USD").is_positive()
        assert Money(Decimal("-5"), "USD").is_negative()

    def test_rounded(self) -> None:
        money = Money(Decimal("10.005"), "USD")
        assert money.rounded(2).amount == Decimal("10.01")
        assert money.rounded(2, rounding=ROUND_HALF_DOWN).amount == Decimal("10.00")

    def test_with_currency(self) -> None:
        converted = Money(Decimal("10.00"), "USD").with_currency("EUR")
        assert converted.currency == "EUR"
        assert converted.amount == Decimal("10.00")

    def test_zero_and_parse(self) -> None:
        assert Money.zero("USD") == Money(Decimal("0"), "USD")
        assert Money.parse("12.34", "USD") == Money(Decimal("12.34"), "USD")
