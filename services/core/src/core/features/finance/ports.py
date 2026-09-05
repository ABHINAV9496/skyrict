"""Finance ports - persistence, cross-module, audit, and event contracts.

Declares what the repository must offer so the service depends on these
Protocols (hexagonal "ports") rather than concrete SQLAlchemy/db/event
implementations. Feature modules may NOT import ``core.models`` / ``core.db``
(import-linter), so:

- ``FinanceRepositoryPort`` is implemented by ``FinanceRepository`` (same
  feature package - no layer violation);
- ``AuditSink`` is implemented structurally by
  ``core.features.audit.repository`` (duck-typed - that module never imports
  this one, so there is no reverse dependency);
- ``FinanceEventSink`` is implemented structurally by
  ``core.events.producers.finance_events.FinanceEventPublisher``;
- ``InvoicePort`` is the seam the future CRM/sales module calls to bill a
  sales order - it ships with a test double until CRM lands (finance never
  reads sales tables; it only receives the ``SalesOrderForInvoicing`` DTO).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from core.domain.entities import (
        AccountCodeSuggestion,
        AiFinanceAnomaly,
        AiFinanceSuggestion,
        ArAging,
        BalanceSheet,
        CashflowProjection,
        ChartOfAccount,
        CloseChecklist,
        ComparativePnl,
        DuplicateGroup,
        FiscalPeriod,
        HealthScore,
        Invoice,
        JournalEntry,
        Payment,
        ProfitAndLoss,
        TenantSetting,
        TrialBalance,
        WorkingCapitalAlert,
    )
    from core.domain.value_objects import EntryStatus, InvoiceStatus


# ---------------------------------------------------------------------------
# Cross-module DTOs - the agreed data shape between finance and CRM/sales.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SalesOrderLine:
    """One line of a sales order, as seen by finance.

    ``account_id`` is the revenue account to post against. When omitted, the
    service resolves the tenant's standard Revenue account (code ``4000``).
    """

    description: str
    account_id: uuid.UUID | None
    quantity: Decimal
    unit_price: Decimal


@dataclass(frozen=True)
class SalesOrderForInvoicing:
    """A sales order ready to be billed - the ONLY thing finance accepts.

    ``order_id`` becomes ``source_ref`` with ``source='sales_order'``; the DB
    ``UNIQUE (tenant_id, source, source_ref)`` lock makes a replayed handoff
    return the existing invoice instead of billing twice.
    """

    tenant_id: uuid.UUID
    order_id: str
    customer_id: uuid.UUID
    invoice_date: date
    due_date: date
    lines: tuple[SalesOrderLine, ...] = field(default_factory=tuple)
    currency: str = "USD"


# ---------------------------------------------------------------------------
# Finance repository port
# ---------------------------------------------------------------------------


class FinanceRepositoryPort(Protocol):
    """Persistence contract for the finance feature (only DB-touching code)."""

    # --- Chart of accounts ---
    async def create_account(self, account: ChartOfAccount) -> ChartOfAccount: ...

    async def get_account_by_id(
        self, account_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ChartOfAccount | None: ...

    async def get_account_by_code(
        self, code: str, tenant_id: uuid.UUID
    ) -> ChartOfAccount | None: ...

    async def list_accounts(
        self, tenant_id: uuid.UUID, *, include_inactive: bool = False
    ) -> Sequence[ChartOfAccount]: ...

    async def deactivate_account(
        self, account_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ChartOfAccount | None: ...

    # --- Journal entries (header + lines, one transaction) ---
    async def create_journal_entry(self, entry: JournalEntry) -> JournalEntry: ...

    async def get_journal_entry(
        self, entry_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> JournalEntry | None: ...

    async def list_journal_entries(
        self,
        tenant_id: uuid.UUID,
        *,
        status: EntryStatus | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[JournalEntry]: ...

    async def post_journal_entry(
        self,
        entry_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        posted_by_user_id: uuid.UUID,
        posted_at: datetime,
    ) -> JournalEntry | None: ...

    async def void_journal_entry(
        self,
        entry_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        voided_at: datetime,
    ) -> JournalEntry | None: ...

    # --- Fiscal periods ---
    async def create_fiscal_period(self, period: FiscalPeriod) -> FiscalPeriod: ...

    async def list_fiscal_periods(self, tenant_id: uuid.UUID) -> Sequence[FiscalPeriod]: ...

    async def close_fiscal_period(
        self, period_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> FiscalPeriod | None: ...

    async def is_period_closed(self, entry_date: date, tenant_id: uuid.UUID) -> bool: ...

    # --- Invoices (header + lines) ---
    async def create_invoice(self, invoice: Invoice) -> Invoice: ...

    async def get_invoice(self, invoice_id: uuid.UUID, tenant_id: uuid.UUID) -> Invoice | None: ...

    async def get_invoice_by_source_ref(
        self, source: str, source_ref: str, tenant_id: uuid.UUID
    ) -> Invoice | None: ...

    async def list_invoices(
        self,
        tenant_id: uuid.UUID,
        *,
        status: InvoiceStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[Invoice]: ...

    async def issue_invoice(
        self, invoice_id: uuid.UUID, tenant_id: uuid.UUID, *, issued_at: datetime
    ) -> Invoice | None: ...

    async def approve_invoice(
        self, invoice_id: uuid.UUID, tenant_id: uuid.UUID, *, approved_at: datetime
    ) -> Invoice | None: ...

    async def void_invoice(
        self, invoice_id: uuid.UUID, tenant_id: uuid.UUID, *, voided_at: datetime
    ) -> Invoice | None: ...

    async def mark_invoice_paid(
        self, invoice_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Invoice | None: ...

    # --- Payments ---
    async def create_payment(self, payment: Payment) -> Payment: ...

    async def get_payment(self, payment_id: uuid.UUID, tenant_id: uuid.UUID) -> Payment | None: ...

    async def get_payment_by_source_ref(
        self, source: str, source_ref: str, tenant_id: uuid.UUID
    ) -> Payment | None: ...

    async def sum_payments_for_invoice(
        self, invoice_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Decimal: ...

    # --- Numbering (nextval on seq_erp_invoice_number / seq_erp_payment_number) ---
    async def next_invoice_number(self, tenant_id: uuid.UUID, year: int) -> str: ...

    async def next_payment_number(self, tenant_id: uuid.UUID, year: int) -> str: ...

    # --- Reports (derived from posted lines, never stored) ---
    async def trial_balance(self, tenant_id: uuid.UUID, as_of: date) -> TrialBalance: ...

    async def profit_and_loss(
        self, tenant_id: uuid.UUID, from_date: date, to_date: date
    ) -> ProfitAndLoss: ...

    async def balance_sheet(self, tenant_id: uuid.UUID, as_of: date) -> BalanceSheet: ...

    async def ar_aging(self, tenant_id: uuid.UUID, as_of: date) -> ArAging: ...

    # --- Automation ports (SKY-56/SKY-64) ---

    async def close_checklist(
        self, tenant_id: uuid.UUID, period_id: uuid.UUID
    ) -> CloseChecklist: ...

    async def duplicates(self, tenant_id: uuid.UUID) -> Sequence[DuplicateGroup]: ...

    async def suggest_account_code(
        self, tenant_id: uuid.UUID, description: str
    ) -> AccountCodeSuggestion: ...

    async def working_capital_alert(
        self, tenant_id: uuid.UUID, as_of: date
    ) -> WorkingCapitalAlert: ...

    async def health_score(self, tenant_id: uuid.UUID, as_of: date) -> HealthScore: ...

    async def cashflow_projection(
        self, tenant_id: uuid.UUID, as_of: date
    ) -> CashflowProjection: ...

    async def anomalies(self, tenant_id: uuid.UUID) -> Sequence[AiFinanceAnomaly]: ...

    async def comparative_pnl(
        self,
        tenant_id: uuid.UUID,
        current_from: date,
        current_to: date,
        prior_from: date,
        prior_to: date,
    ) -> ComparativePnl: ...

    async def reverse_journal_entry(
        self,
        entry_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        reversed_by_user_id: uuid.UUID,
        reversed_at: datetime,
    ) -> JournalEntry | None: ...

    # --- Tenant settings (KV store) ---

    async def get_tenant_setting(self, tenant_id: uuid.UUID, key: str) -> TenantSetting | None: ...

    async def upsert_tenant_setting(
        self, tenant_id: uuid.UUID, key: str, value: str
    ) -> TenantSetting: ...

    # --- AI suggestion persistence ---

    async def upsert_ai_suggestion(
        self, tenant_id: uuid.UUID, suggestion: AiFinanceSuggestion
    ) -> AiFinanceSuggestion: ...

    async def upsert_ai_anomaly(
        self, tenant_id: uuid.UUID, anomaly: AiFinanceAnomaly
    ) -> AiFinanceAnomaly: ...

    async def list_open_ai_anomalies(self, tenant_id: uuid.UUID) -> Sequence[AiFinanceAnomaly]: ...

    # --- AI anomaly lookup by ID ---

    async def get_ai_anomaly(
        self, tenant_id: uuid.UUID, anomaly_id: uuid.UUID
    ) -> AiFinanceAnomaly | None: ...

    # --- Overdue invoices for batch reminders ---

    async def list_invoices_overdue(self, tenant_id: uuid.UUID) -> Sequence[Invoice]: ...

    # --- Invoice lookup ---

    async def get_invoice_by_id(
        self, tenant_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> Invoice | None: ...


# ---------------------------------------------------------------------------
# Cross-module invoicing port (seam for CRM/sales)
# ---------------------------------------------------------------------------


class InvoicePort(Protocol):
    """Billing seam the CRM/sales module calls when an order is ready to bill.

    Implemented by the finance service (via ``FinanceService.create_from_order``)
    and stubbed with a test double in unit tests until CRM lands. Idempotent:
    re-billing the same ``order_id`` returns the existing invoice.
    """

    async def create_from_order(self, order: SalesOrderForInvoicing) -> Invoice: ...


# ---------------------------------------------------------------------------
# Audit sink (implemented structurally by core.features.audit.repository)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Cross-module customer port (seam for CRM)
# ---------------------------------------------------------------------------


class CustomerPort(Protocol):
    """Customer name resolution port - finance reads customer names, never CRM tables.

    Implemented by ``CrmRepository`` (via ``get_customer``). The service calls
    ``get_customer_name`` to resolve a single customer, or the batch variant
    ``get_customer_names`` for list endpoints to avoid N+1 queries.
    """

    async def get_customer_name(
        self, customer_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> str | None: ...

    async def get_customer_names(
        self, customer_ids: Sequence[uuid.UUID], *, tenant_id: uuid.UUID
    ) -> dict[uuid.UUID, str]: ...


# ---------------------------------------------------------------------------
# Cross-module COGS port (seam for sales/inventory)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CogsLine:
    """One consumed product line for COGS posting.

    ``unit_cost`` is the product's cost price at fulfilment time.
    """

    product_id: uuid.UUID
    quantity: Decimal
    unit_cost: Decimal


class CogsPort(Protocol):
    """Cost-of-goods-sold posting seam the sales service calls after stock consumption.

    Implemented by the finance service (via ``FinanceService.post_cogs_for_order``).
    """

    async def post_cogs_for_order(
        self,
        *,
        tenant_id: uuid.UUID,
        order_id: str,
        entry_date: date,
        lines: Sequence[CogsLine],
    ) -> None: ...


@dataclass(frozen=True)
class PayrollAccrualOutcome:
    """Result of a payroll accrual JE-draft attempt (HR-AUT-001, Commit 4).

    ``missing_accounts`` lists the chart codes the tenant has not seeded — the
    payroll service flips the run to ``je_bridge_status='pending'`` when it is
    non-empty so the gap is queryable instead of silently losing the booking.
    ``entry_id`` is set when a DRAFT entry was created (or already existed for
    the same ``(source='payroll', source_ref=run_id)`` idempotency key).
    """

    entry_id: uuid.UUID | None = None
    missing_accounts: tuple[str, ...] = ()
    already_booked: bool = False


class PayrollAccrualPort(Protocol):
    """Payroll→Finance accrual seam — implemented by ``FinanceService``.

    Called by the payroll service when a run is marked PAID (flag-gated by
    ``erp_payroll_settings.je_bridge_enabled``). The entry is created as a
    DRAFT in the Finance inbox so posting/approval stays on the existing
    finance endpoints today and is consumed later by FIN-AI-001 — the payroll
    feature never imports finance modules, mirroring the COGS seam above.
    """

    async def create_payroll_accrual_draft(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        entry_date: date,
        gross: Decimal,
        net: Decimal,
    ) -> PayrollAccrualOutcome: ...


# ---------------------------------------------------------------------------
# Cross-module CRM timeline port (seam for writing finance events to CRM)
# ---------------------------------------------------------------------------


class FinanceTimelinePort(Protocol):
    """Write curated finance events to the customer-facing CRM timeline.

    Implemented structurally by ``CrmRepository.record_timeline_event`` -
    the finance service never imports CRM modules. Events are anchored to
    the customer entity (``entity_type='customer'``).
    """

    async def record_timeline_event(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_type: Any,
        entity_id: uuid.UUID,
        event_type: Any,
        title: str,
        actor_id: uuid.UUID | None = None,
        payload: dict[str, object] | None = None,
    ) -> Any: ...


# ---------------------------------------------------------------------------
# Cross-module order lookup port (seam for resolving source sales order)
# ---------------------------------------------------------------------------


class OrderLookupPort(Protocol):
    """Resolve a sales order number from its UUID for display on invoice detail.

    Implemented structurally by ``SalesRepository.get_order`` - finance never
    imports the sales feature.
    """

    async def get_order(self, order_id: uuid.UUID, *, tenant_id: uuid.UUID) -> Any: ...


# ---------------------------------------------------------------------------
# Audit sink (implemented structurally by core.features.audit.repository)
# ---------------------------------------------------------------------------


class AuditSink(Protocol):
    """Append-only audit trail for finance state changes.

    Written in the SAME request transaction as the state change so the audit
    row commits atomically with the business mutation (identity's pattern).
    """

    async def log(
        self,
        *,
        tenant_id: str | uuid.UUID,
        user_id: str | uuid.UUID | None,
        action: str,
        target: str,
        details: dict[str, Any] | None = None,
    ) -> None: ...


# ---------------------------------------------------------------------------
# Event sink (implemented structurally by core.events.producers.finance_events)
# ---------------------------------------------------------------------------


class FinanceEventSink(Protocol):
    """Outbound event announcements for finance money moments.

    Implementations buffer events and publish them only AFTER the request
    transaction commits (session ``after_commit``) so consumers never observe
    money that did not actually persist.
    """

    def journal_entry_posted(
        self,
        *,
        entry_id: uuid.UUID,
        tenant_id: uuid.UUID,
        correlation_id: str,
    ) -> None: ...

    def invoice_created(
        self,
        *,
        invoice_id: uuid.UUID,
        invoice_number: str,
        tenant_id: uuid.UUID,
        correlation_id: str,
    ) -> None: ...

    def invoice_approved(
        self,
        *,
        invoice_id: uuid.UUID,
        invoice_number: str,
        revenue_entry_id: uuid.UUID,
        tenant_id: uuid.UUID,
        correlation_id: str,
    ) -> None: ...

    def payment_applied(
        self,
        *,
        payment_id: uuid.UUID,
        payment_number: str,
        invoice_id: uuid.UUID,
        tenant_id: uuid.UUID,
        correlation_id: str,
    ) -> None: ...
