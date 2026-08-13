"""Value objects — immutable, identity-less domain concepts.

``Money`` is the single representation of monetary amounts in every ERP module.
It is a pure-domain object: no framework, no database. The currency set mirrors
the ISO 4217 codes seeded into the ``erp_currencies`` table by migration 0001 —
the table exists for FK constraints and reference lookups, while validation at
construction stays here so the domain layer never touches the DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum

from skyrict_common.exceptions import ValidationError

# ISO 4217 alpha-3 codes matching the erp_currencies seed in migration 0001.
SUPPORTED_CURRENCIES: frozenset[str] = frozenset(
    {
        "USD",
        "EUR",
        "GBP",
        "JPY",
        "CHF",
        "CAD",
        "AUD",
        "NZD",
        "INR",
        "CNY",
        "SGD",
        "HKD",
        "SEK",
        "NOK",
        "DKK",
        "PLN",
        "BRL",
        "MXN",
        "ZAR",
        "AED",
    }
)

# Decimal precision/rounding applied by rounded() and arithmetic results.
_MONEY_QUANTUM = Decimal("0.01")


class StockMovementType(StrEnum):
    """Native PostgreSQL enum backing ``erp_stock_movements.movement_type``.

    The ledger distinguishes the buckets that feed the materialized stock level:
    ``qty_on_hand`` sums everything EXCEPT ``reservation``/``release``, while
    ``qty_reserved`` is the net of those two. ``transfer`` is recorded as a
    dual-row pair (negative at the source warehouse, positive at the
    destination) sharing one ``(ref_type, ref_id)`` — allowed because the
    idempotency key also includes ``warehouse_id``.
    """

    RECEIPT = "receipt"
    ISSUE = "issue"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"
    RESERVATION = "reservation"
    RELEASE = "release"


class AccountType(StrEnum):
    """Native PostgreSQL enum backing ``erp_chart_of_accounts.account_type``.

    The five DEALER account categories. The trial balance and P&L group
    accounts by these buckets and use them to decide whether a balance is
    shown as a debit (asset/expense) or a credit (liability/equity/revenue).
    """

    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class EntryStatus(StrEnum):
    """Native PostgreSQL enum backing ``erp_journal_entries.status``.

    An entry is not real money until ``posted``. ``voided`` is pre-post
    cancellation only in v1 (reversal entries arrive in v1.1).
    """

    DRAFT = "draft"
    POSTED = "posted"
    VOIDED = "voided"


class InvoiceStatus(StrEnum):
    """Native PostgreSQL enum backing ``erp_invoices.status``.

    Revenue is recognized only at ``approved`` (accrual basis); ``paid`` moves
    cash and reduces receivables. ``voided`` is allowed from draft/issued only.
    """

    DRAFT = "draft"
    ISSUED = "issued"
    APPROVED = "approved"
    PAID = "paid"
    VOIDED = "voided"


class PaymentStatus(StrEnum):
    """Native PostgreSQL enum backing ``erp_payments.status``.

    v1 has a single state; a reversal payment adds a state in v1.1.
    """

    APPLIED = "applied"


def _require_currency(currency: str) -> None:
    """Validate a currency code against the supported ISO 4217 set."""
    normalized = currency.strip().upper()
    if normalized not in SUPPORTED_CURRENCIES:
        raise ValidationError(f"Unsupported currency: '{currency}'")
    return None


@dataclass(frozen=True)
class Money:
    """Immutable monetary value — Decimal amount + ISO 4217 currency.

    Arithmetic is Decimal-only and same-currency: mixing currencies raises
    ``ValidationError`` so a naive ``usd + eur`` can never silently corrupt an
    ERP total. Use :meth:`convert` or an explicit FX step for cross-currency.
    """

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            object.__setattr__(
                self,
                "amount",
                Decimal(str(self.amount)),
            )
        try:
            normalized = Decimal(self.amount).normalize()
            if not normalized.is_finite():
                raise ValidationError("Money amount must be a finite decimal")
        except InvalidOperation as exc:
            raise ValidationError(f"Money amount is not a valid decimal: {self.amount}") from exc
        _require_currency(self.currency)
        object.__setattr__(self, "currency", self.currency.strip().upper())

    # ------------------------------------------------------------------
    # Arithmetic (same-currency only)
    # ------------------------------------------------------------------

    def _assert_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValidationError(f"Cannot combine currencies: {self.currency} != {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __mul__(self, multiplier: Decimal | int | str) -> Money:
        try:
            factor = Decimal(multiplier)
        except InvalidOperation as exc:
            raise ValidationError(f"Invalid multiplier: {multiplier}") from exc
        return Money(amount=(self.amount * factor), currency=self.currency)

    __rmul__ = __mul__

    def __truediv__(self, divisor: Decimal | int | str) -> Money:
        try:
            factor = Decimal(divisor)
        except InvalidOperation as exc:
            raise ValidationError(f"Invalid divisor: {divisor}") from exc
        if factor == 0:
            raise ValidationError("Cannot divide Money by zero")
        return Money(amount=(self.amount / factor), currency=self.currency)

    def __neg__(self) -> Money:
        return Money(amount=-self.amount, currency=self.currency)

    def __abs__(self) -> Money:
        return Money(amount=abs(self.amount), currency=self.currency)

    # ------------------------------------------------------------------
    # Ordering (same-currency only)
    # ------------------------------------------------------------------

    def __lt__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount >= other.amount

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.amount == other.amount and self.currency == other.currency

    def __hash__(self) -> int:
        return hash((self.amount, self.currency))

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def to_decimal(self) -> Decimal:
        """Return the raw Decimal amount (drop the currency tag)."""
        return self.amount

    def is_zero(self) -> bool:
        return self.amount == 0

    def is_positive(self) -> bool:
        return self.amount > 0

    def is_negative(self) -> bool:
        return self.amount < 0

    def rounded(self, digits: int = 2, rounding: str = ROUND_HALF_UP) -> Money:
        """Return a copy rounded to ``digits`` decimal places."""
        quantum = Decimal(1).scaleb(-digits)
        return Money(
            amount=self.amount.quantize(quantum, rounding=rounding), currency=self.currency
        )

    def with_currency(self, currency: str) -> Money:
        """Return the same amount tagged with a new currency."""
        _require_currency(currency)
        return Money(amount=self.amount, currency=currency)

    @classmethod
    def zero(cls, currency: str = "USD") -> Money:
        """Construct a zero amount in the given currency."""
        return cls(amount=Decimal("0"), currency=currency)

    @classmethod
    def parse(cls, amount: str | int | float | Decimal, currency: str) -> Money:
        """Construct from a string/int/float/Decimal without rounding surprises."""
        return cls(amount=Decimal(str(amount)), currency=currency)

    def __repr__(self) -> str:
        return f"Money({self.amount}, {self.currency!r})"

    def __str__(self) -> str:
        return f"{self.currency} {self.amount}"
