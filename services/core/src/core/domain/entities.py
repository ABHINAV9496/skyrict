"""Domain entities — pure Python, no framework dependencies.

These are the in-memory representations the repository layer maps ORM models
to/from. They are plain (immutable) dataclasses so services can reason about
tenant-scoped RBAC grants without touching SQLAlchemy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from core.domain.value_objects import Money

if TYPE_CHECKING:
    import uuid
    from datetime import date, datetime

    from core.domain.value_objects import (
        AccountType,
        EntryStatus,
        InvoiceStatus,
        PaymentStatus,
        StockMovementType,
    )


@dataclass(frozen=True)
class CorePermission:
    """A platform-fixed permission key (e.g. ``erp.invoice.read``).

    Global — not tenant-scoped: the catalog is the same for every tenant.
    """

    key: str
    description: str = ""


@dataclass(frozen=True)
class CoreRole:
    """A tenant-scoped role holding a set of permission grants.

    ``permissions`` holds granted permission keys. The wildcard ``"*"`` grants
    every key in the catalog (owner role).
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    permissions: tuple[str, ...] = ()
    is_system_role: bool = False


@dataclass(frozen=True)
class CoreUserRole:
    """A tenant-scoped grant of one role to one user.

    ``user_id`` references an identity-service user (no FK at the DB level —
    identity owns users).
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role_id: uuid.UUID
    scope_id: uuid.UUID | None = field(default=None)


@dataclass(frozen=True)
class Product:
    """A tenant-scoped sellable/countable item (soft-deletable via ``is_active``).

    Prices are ``Money`` amounts so currency validation happens at construction,
    and the ORM layer splits them into a Numeric column + currency code.
    """

    tenant_id: uuid.UUID
    sku: str
    name: str
    category: str | None = None
    unit: str | None = None
    cost_price: Money = field(default_factory=lambda: Money.zero("USD"))
    sell_price: Money = field(default_factory=lambda: Money.zero("USD"))
    reorder_point: Decimal = Decimal("0")
    is_active: bool = True
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class Warehouse:
    """A tenant-scoped storage location (soft-deletable via ``is_active``)."""

    tenant_id: uuid.UUID
    name: str
    location: str | None = None
    is_active: bool = True
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class StockLevel:
    """Materialized current stock for one product in one warehouse.

    ``qty_on_hand`` = ledger sum of non-reservation movements; ``qty_reserved``
    = net of reservation/release movements. The DB CHECK ``0 <= qty_reserved
    <= qty_on_hand`` makes over-reservation impossible at the constraint level.
    """

    tenant_id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    qty_on_hand: Decimal = Decimal("0")
    qty_reserved: Decimal = Decimal("0")
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class StockMovement:
    """One immutable ledger entry — insert-only, never updated or deleted.

    ``qty`` is signed (negative for issues/outflows). ``(ref_type, ref_id)``
    identifies the source document line for idempotency probes; combined with
    ``warehouse_id`` it is unique per tenant so a transfer pair can share a ref.
    """

    tenant_id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    movement_type: StockMovementType
    qty: Decimal
    ref_type: str
    ref_id: str
    id: uuid.UUID | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class ChartOfAccount:
    """One account in a tenant's chart of accounts (soft-deletable).

    ``code`` is unique per tenant and is the key the journal entry API accepts
    (``UNIQUE (tenant_id, code)``). Accounts referenced by history are never
    hard-deleted (composite FKs use RESTRICT); ``is_active`` is the removal path.
    """

    tenant_id: uuid.UUID
    code: str
    name: str
    account_type: AccountType
    is_active: bool = True
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class JournalLine:
    """One side of a double-entry journal transaction.

    Exactly one of ``debit`` / ``credit`` must be set (DB CHECK XOR), the amount
    must be non-zero and non-negative. Balance is NOT enforced here — drafts may
    be unbalanced; the service enforces balance only at ``post``.
    """

    account_id: uuid.UUID
    debit: Decimal | None = None
    credit: Decimal | None = None
    currency: str = "USD"
    id: uuid.UUID | None = None


@dataclass(frozen=True)
class JournalEntry:
    """The header of one double-entry transaction.

    ``(source, source_ref)`` is the idempotency stamp: the DB ``UNIQUE (tenant_id,
    source, source_ref)`` means a replayed request (e.g. an invoice accrual) can
    never create a second entry. Manual entries use ``source_ref = None``.
    """

    tenant_id: uuid.UUID
    entry_date: date
    memo: str | None
    status: EntryStatus
    source: str
    source_ref: str | None
    lines: tuple[JournalLine, ...] = ()
    id: uuid.UUID | None = None
    posted_at: datetime | None = None
    posted_by_user_id: uuid.UUID | None = None
    voided_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class InvoiceLine:
    """One line item of an invoice (``amount = quantity * unit_price``)."""

    invoice_id: uuid.UUID | None
    line_no: int
    description: str
    account_id: uuid.UUID
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    id: uuid.UUID | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class Invoice:
    """An accounts-receivable document (bill to a customer).

    Revenue is recognized only at ``approved`` (accrual). ``(source, source_ref)``
    is the idempotency stamp for ``InvoicePort.create_from_order`` (source =
    ``sales_order``); manual invoices default to source = ``manual`` with a NULL
    source_ref so unlimited manual bills stay allowed.
    """

    tenant_id: uuid.UUID
    invoice_number: str
    customer_id: uuid.UUID
    invoice_date: date
    due_date: date
    status: InvoiceStatus
    total: Decimal
    source: str
    source_ref: str | None
    lines: tuple[InvoiceLine, ...] = ()
    id: uuid.UUID | None = None
    issued_at: datetime | None = None
    approved_at: datetime | None = None
    voided_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class Payment:
    """A cash receipt applied to an invoice (DR Cash / CR AR).

    ``(source, source_ref)`` is the second idempotency lock — a replayed
    ``apply_payment`` can never double-book.
    """

    tenant_id: uuid.UUID
    payment_number: str
    invoice_id: uuid.UUID
    amount: Decimal
    method: str
    paid_at: datetime
    status: PaymentStatus
    source: str
    source_ref: str | None
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class FiscalPeriod:
    """An accounting period that can be closed to freeze history.

    An entry belongs to a period by ``entry_date`` range, not by FK; the
    closed-period gate compares dates.
    """

    tenant_id: uuid.UUID
    name: str
    start_date: date
    end_date: date
    is_closed: bool = False
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Report read-models (derived from posted journal lines — never stored).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrialBalanceRow:
    account_id: uuid.UUID
    code: str
    name: str
    account_type: AccountType
    debit: Decimal
    credit: Decimal


@dataclass(frozen=True)
class TrialBalance:
    as_of: date
    rows: tuple[TrialBalanceRow, ...]
    total_debit: Decimal
    total_credit: Decimal


@dataclass(frozen=True)
class PnlLine:
    account_id: uuid.UUID
    code: str
    name: str
    amount: Decimal


@dataclass(frozen=True)
class ProfitAndLoss:
    from_date: date
    to_date: date
    revenue: tuple[PnlLine, ...]
    expenses: tuple[PnlLine, ...]
    total_revenue: Decimal
    total_expenses: Decimal
    net_income: Decimal


@dataclass(frozen=True)
class BalanceSheetLine:
    account_id: uuid.UUID
    code: str
    name: str
    balance: Decimal


@dataclass(frozen=True)
class BalanceSheet:
    as_of: date
    assets: tuple[BalanceSheetLine, ...]
    liabilities: tuple[BalanceSheetLine, ...]
    equity: tuple[BalanceSheetLine, ...]
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
