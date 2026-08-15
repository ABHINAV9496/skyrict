"""Domain entities — pure Python, no framework dependencies.

These are the in-memory representations the repository layer maps ORM models
to/from. They are plain (immutable) dataclasses so services can reason about
tenant-scoped RBAC grants without touching SQLAlchemy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from core.domain.value_objects import (
    CreditCheckResult,
    LeadStatus,
    Money,
    OpportunityStage,
    OrderStatus,
)

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


# ---------------------------------------------------------------------------
# CRM entities (leads, opportunities, customers) — CRM-DATA-001
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Lead:
    """An inbound inquiry before it has pipeline value.

    Owner/team-scoped: ``owner_id`` and ``team_id`` are plain UUID references
    to identity users (and a future teams model), resolved through ports at
    the service layer. ``email`` is deliberately not unique — dedupe is a
    soft probe at the service layer.
    """

    tenant_id: uuid.UUID
    status: LeadStatus = LeadStatus.NEW
    source: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    owner_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class Opportunity:
    """A pipeline deal — moves through stages and terminates won/lost.

    Deliberately customer-less in Phase 1 (a won opportunity is promoted to a
    customer by the service layer). ``amount`` is optional until the deal has
    value; when present it is a ``Money`` so the currency tag travels with it.
    ``won_at`` / ``lost_at`` are set exactly on the terminal transition.
    """

    tenant_id: uuid.UUID
    name: str
    stage: OpportunityStage = OpportunityStage.PROSPECTING
    amount: Money | None = None
    probability: int = 0
    expected_close_date: date | None = None
    owner_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    won_at: datetime | None = None
    lost_at: datetime | None = None
    lost_reason: str | None = None
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class Customer:
    """An account we do business with.

    Soft-deleted via ``is_active`` (the ERP convention — no status enum).
    ``customer_code`` is the stable per-tenant external key. A NULL
    ``credit_limit`` means "no limit"; when present it is a ``Money`` so the
    currency tag travels with it.
    """

    tenant_id: uuid.UUID
    customer_code: str
    name: str
    email: str | None = None
    phone: str | None = None
    credit_limit: Money | None = None
    is_active: bool = True
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Sales entities (orders, order lines) — CRM-DATA-001
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SalesOrder:
    """A customer commitment — the money record handed to finance.

    ``status`` follows ``draft -> confirmed -> fulfilled`` (``cancelled``
    terminal). The money columns are a cached projection: the service
    recomputes them from the lines on every write (CRM-BE-002) — never
    trusted from clients. ``credit_check`` records the confirm-time result.
    """

    tenant_id: uuid.UUID
    order_number: str
    customer_id: uuid.UUID
    status: OrderStatus = OrderStatus.DRAFT
    credit_check: CreditCheckResult = CreditCheckResult.PENDING
    subtotal: Money = field(default_factory=lambda: Money.zero("USD"))
    discount: Money = field(default_factory=lambda: Money.zero("USD"))
    tax: Money = field(default_factory=lambda: Money.zero("USD"))
    total: Money = field(default_factory=lambda: Money.zero("USD"))
    confirmed_at: datetime | None = None
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class SalesOrderLine:
    """One line of a sales order.

    ``product_name`` / ``sku`` are denormalized snapshots taken at order time
    so history stays stable even if the product catalog changes. Per-line
    prices are plain Decimals (the currency lives on the order header);
    ``line_total`` is a cached projection recomputed by the service.

    ``order_id`` is None on a line being created (the repository stamps the
    generated header id on write — mirroring ``InvoiceLine.invoice_id``) and
    always populated on read.
    """

    tenant_id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    sku: str
    quantity: Decimal
    order_id: uuid.UUID | None = None
    unit_price: Decimal = Decimal("0")
    discount: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    line_total: Decimal = Decimal("0")
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
