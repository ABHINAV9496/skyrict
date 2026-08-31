"""Finance service — the feature's business rules and money-moment announcements.

The only orchestrator in the finance module. Depends on Protocols
(:class:`FinanceRepositoryPort`, :class:`AuditSink`, :class:`FinanceEventSink`)
so it never touches SQLAlchemy; the API composition root wires the concrete
repository, audit repository, and after-commit event publisher (see
``core.api.deps``).

Rules owned here (mirroring the DB CHECK constraints as early validation):

- **Double entry**: a journal entry is balanced at POST time only (drafts may
  be unbalanced); posting into a closed fiscal period is rejected.
- **Lifecycles**: entries are draft -> posted / voided; invoices are draft ->
  issued -> approved -> paid, with void allowed only from draft/issued;
  revenue is recognized ONLY at ``approved`` (accrual), which writes a POSTED
  accrual entry (DR AR / CR revenue) stamped ``(source='invoice', source_ref=
  invoice_id)`` — the unique lock that makes double-approval impossible.
- **Idempotency**: ``create_from_order`` re-bills an order by returning the
  existing invoice; payments cannot exceed the outstanding balance.
- **Money moments**: every irreversible state change is audited (same
  transaction) and announced through the event sink (after commit).

``create_from_order`` is the :class:`InvoicePort` implementation CRM/sales will
call — finance only ever receives the ``SalesOrderForInvoicing`` DTO, never a
sales table.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from core.core import audit_events
from core.core.constants import (
    ACCRUED_SALARIES_PAYABLE_ACCOUNT_CODE,
    AR_ACCOUNT_CODE,
    COGS_ACCOUNT_CODE,
    DEDUCTIONS_PAYABLE_ACCOUNT_CODE,
    INVENTORY_ASSET_ACCOUNT_CODE,
    INVOICE_SOURCE_MANUAL,
    INVOICE_SOURCE_SALES_ORDER,
    JOURNAL_SOURCE_COGS,
    JOURNAL_SOURCE_INVOICE,
    JOURNAL_SOURCE_MANUAL,
    JOURNAL_SOURCE_PAYROLL,
    PAYMENT_SOURCE_MANUAL,
    REVENUE_ACCOUNT_CODE,
    SALARY_EXPENSE_ACCOUNT_CODE,
)
from core.domain.entities import (
    BalanceSheet,
    ChartOfAccount,
    FiscalPeriod,
    Invoice,
    InvoiceLine,
    JournalEntry,
    JournalLine,
    Payment,
    ProfitAndLoss,
    TrialBalance,
)
from core.domain.value_objects import (
    AccountType,
    CrmEntityType,
    CrmTimelineEventType,
    EntryStatus,
    InvoiceStatus,
    PaymentStatus,
)
from skyrict_common.exceptions import ConflictError, NotFoundError, ValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from core.features.finance.ports import (
        AuditSink,
        CogsLine,
        CustomerPort,
        FinanceEventSink,
        FinanceRepositoryPort,
        FinanceTimelinePort,
        OrderLookupPort,
        SalesOrderForInvoicing,
    )

from core.features.finance.ports import PayrollAccrualOutcome

# Maximum scale for line amounts, kept in sync with the Numeric(18, 4) columns.
_MONEY_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class JournalLineInput:
    """One requested leg of a manual journal entry (account identified by code)."""

    account_code: str
    debit: Decimal | None = None
    credit: Decimal | None = None


@dataclass(frozen=True)
class InvoiceLineInput:
    """One requested line item of a manual invoice."""

    description: str
    account_code: str
    quantity: Decimal
    unit_price: Decimal


class FinanceService:
    """Business rules for chart of accounts, journaling, invoices, payments, reports."""

    def __init__(
        self,
        repo: FinanceRepositoryPort,
        audit: AuditSink,
        events: FinanceEventSink,
        *,
        correlation_id: str | None = None,
        customers: CustomerPort | None = None,
        timeline: FinanceTimelinePort | None = None,
        order_lookup: OrderLookupPort | None = None,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._events = events
        self._correlation_id = correlation_id or str(uuid.uuid4())
        self._customers = customers
        self._timeline = timeline
        self._order_lookup = order_lookup

    # ------------------------------------------------------------------
    # Chart of accounts
    # ------------------------------------------------------------------

    async def create_account(
        self,
        *,
        tenant_id: uuid.UUID,
        code: str,
        name: str,
        account_type: AccountType,
    ) -> ChartOfAccount:
        account = ChartOfAccount(
            tenant_id=tenant_id,
            code=code.strip().upper(),
            name=name,
            account_type=account_type,
        )
        created = await self._repo.create_account(account)
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=None,
            action=audit_events.FINANCE_CHART_OF_ACCOUNTS_CREATED,
            target=f"chart_of_account:{created.id}",
            details={"code": created.code, "name": created.name},
        )
        return created

    async def list_accounts(
        self, tenant_id: uuid.UUID, *, include_inactive: bool = False
    ) -> Sequence[ChartOfAccount]:
        return await self._repo.list_accounts(tenant_id, include_inactive=include_inactive)

    async def deactivate_account(
        self, tenant_id: uuid.UUID, account_id: uuid.UUID
    ) -> ChartOfAccount:
        deactivated = await self._repo.deactivate_account(account_id, tenant_id)
        if deactivated is None:
            raise NotFoundError(f"Account {account_id} not found")
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=None,
            action=audit_events.FINANCE_CHART_OF_ACCOUNTS_DEACTIVATED,
            target=f"chart_of_account:{deactivated.id}",
            details={"code": deactivated.code},
        )
        return deactivated

    # ------------------------------------------------------------------
    # Journal entries
    # ------------------------------------------------------------------

    async def create_manual_entry(
        self,
        *,
        tenant_id: uuid.UUID,
        entry_date: date,
        memo: str | None,
        lines: Sequence[JournalLineInput],
    ) -> JournalEntry:
        """Create a DRAFT manual entry — balance is only enforced at post."""
        if not lines:
            raise ValidationError("A journal entry must have at least one line")

        resolved: list[JournalLine] = []
        for line in lines:
            account = await self._repo.get_account_by_code(line.account_code, tenant_id)
            if account is None:
                raise NotFoundError(f"Account with code '{line.account_code}' not found")
            if not account.is_active:
                raise ConflictError(f"Account '{line.account_code}' is deactivated")
            assert account.id is not None

            debit = _normalize_amount(line.debit)
            credit = _normalize_amount(line.credit)
            if (debit is None) == (credit is None):
                raise ValidationError(
                    f"Line for account '{line.account_code}' must set exactly one of "
                    "debit or credit"
                )
            amount = debit if debit is not None else credit
            assert amount is not None
            if amount <= 0:
                raise ValidationError(f"Line for account '{line.account_code}' must be > 0")
            resolved.append(JournalLine(account_id=account.id, debit=debit, credit=credit))

        entry = JournalEntry(
            tenant_id=tenant_id,
            entry_date=entry_date,
            memo=memo,
            status=EntryStatus.DRAFT,
            source=JOURNAL_SOURCE_MANUAL,
            source_ref=None,
            lines=tuple(resolved),
        )
        return await self._repo.create_journal_entry(entry)

    async def get_journal_entry(self, tenant_id: uuid.UUID, entry_id: uuid.UUID) -> JournalEntry:
        entry = await self._repo.get_journal_entry(entry_id, tenant_id)
        if entry is None:
            raise NotFoundError(f"Journal entry {entry_id} not found")
        return entry

    async def list_journal_entries(
        self,
        tenant_id: uuid.UUID,
        *,
        status: EntryStatus | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[JournalEntry]:
        return await self._repo.list_journal_entries(
            tenant_id,
            status=status,
            from_date=from_date,
            to_date=to_date,
            offset=offset,
            limit=limit,
        )

    async def post_journal_entry(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        entry_id: uuid.UUID,
    ) -> JournalEntry:
        """Post a draft entry — the moment money becomes real.

        Gates: entry is draft, the entry date's fiscal period is open, and the
        entry balances. On success the entry is audited and the
        ``journal_entry.posted`` money moment is announced (after commit).
        """
        entry = await self.get_journal_entry(tenant_id, entry_id)
        if entry.status != EntryStatus.DRAFT:
            raise ConflictError("Only draft journal entries can be posted")

        if await self._repo.is_period_closed(entry.entry_date, tenant_id):
            raise ConflictError(
                f"Entry date {entry.entry_date.isoformat()} falls in a closed fiscal period"
            )

        debit_total = sum(
            (line.debit or Decimal("0")) for line in entry.lines if line.debit is not None
        )
        credit_total = sum(
            (line.credit or Decimal("0")) for line in entry.lines if line.credit is not None
        )
        if debit_total != credit_total:
            raise ValidationError(
                f"Journal entry is not balanced (debit {debit_total} != credit {credit_total})"
            )

        posted = await self._repo.post_journal_entry(
            entry_id,
            tenant_id,
            posted_by_user_id=user_id,
            posted_at=datetime.now(UTC),
        )
        assert posted is not None

        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=audit_events.FINANCE_JOURNAL_ENTRY_POSTED,
            target=f"journal_entry:{entry_id}",
            details={"entry_date": entry.entry_date.isoformat(), "memo": entry.memo},
        )
        self._events.journal_entry_posted(
            entry_id=entry_id,
            tenant_id=tenant_id,
            correlation_id=self._correlation_id,
        )
        return posted

    async def void_journal_entry(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        entry_id: uuid.UUID,
    ) -> JournalEntry:
        """Void a DRAFT entry (pre-post cancellation only in v1)."""
        entry = await self.get_journal_entry(tenant_id, entry_id)
        if entry.status != EntryStatus.DRAFT:
            raise ConflictError(
                "Only draft journal entries can be voided; posted entries need a "
                "reversing entry (v1.1)"
            )

        voided = await self._repo.void_journal_entry(
            entry_id, tenant_id, voided_at=datetime.now(UTC)
        )
        assert voided is not None

        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=audit_events.FINANCE_JOURNAL_ENTRY_VOIDED,
            target=f"journal_entry:{entry_id}",
            details={"entry_date": entry.entry_date.isoformat()},
        )
        return voided

    # ------------------------------------------------------------------
    # Fiscal periods
    # ------------------------------------------------------------------

    async def create_fiscal_period(
        self,
        *,
        tenant_id: uuid.UUID,
        name: str,
        start_date: date,
        end_date: date,
    ) -> FiscalPeriod:
        if end_date < start_date:
            raise ValidationError("Fiscal period end date must be on or after its start date")
        for existing in await self._repo.list_fiscal_periods(tenant_id):
            if existing.start_date <= end_date and existing.end_date >= start_date:
                raise ConflictError(
                    f"Fiscal period '{name}' overlaps '{existing.name}' "
                    f"({existing.start_date} - {existing.end_date})"
                )

        period = FiscalPeriod(
            tenant_id=tenant_id,
            name=name,
            start_date=start_date,
            end_date=end_date,
        )
        created = await self._repo.create_fiscal_period(period)
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=None,
            action=audit_events.FINANCE_FISCAL_PERIOD_CREATED,
            target=f"fiscal_period:{created.id}",
            details={
                "name": created.name,
                "start_date": created.start_date.isoformat(),
                "end_date": created.end_date.isoformat(),
            },
        )
        return created

    async def list_fiscal_periods(self, tenant_id: uuid.UUID) -> Sequence[FiscalPeriod]:
        return await self._repo.list_fiscal_periods(tenant_id)

    async def close_fiscal_period(self, tenant_id: uuid.UUID, period_id: uuid.UUID) -> FiscalPeriod:
        closed = await self._repo.close_fiscal_period(period_id, tenant_id)
        if closed is None:
            raise NotFoundError(f"Fiscal period {period_id} not found")
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=None,
            action=audit_events.FINANCE_FISCAL_PERIOD_CLOSED,
            target=f"fiscal_period:{period_id}",
            details={"name": closed.name},
        )
        return closed

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------

    async def create_manual_invoice(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        customer_id: uuid.UUID,
        invoice_date: date,
        due_date: date,
        lines: Sequence[InvoiceLineInput],
    ) -> Invoice:
        if not lines:
            raise ValidationError("An invoice must have at least one line")
        if due_date < invoice_date:
            raise ValidationError("Invoice due date must be on or after its invoice date")

        invoice_lines, total = await self._resolve_invoice_lines(tenant_id, lines)
        number = await self._repo.next_invoice_number(tenant_id, invoice_date.year)
        invoice = Invoice(
            tenant_id=tenant_id,
            invoice_number=number,
            customer_id=customer_id,
            invoice_date=invoice_date,
            due_date=due_date,
            status=InvoiceStatus.DRAFT,
            total=total,
            source=INVOICE_SOURCE_MANUAL,
            source_ref=None,
            lines=invoice_lines,
        )
        created = await self._repo.create_invoice(invoice)
        await self._announce_invoice_created(tenant_id, created, user_id=user_id)
        return created

    async def create_from_order(self, order: SalesOrderForInvoicing) -> Invoice:
        """Implement :class:`InvoicePort` — bill a CRM sales order.

        Idempotent per ``order_id``: the ``UNIQUE (tenant_id, source, source_ref)``
        lock returns the existing invoice instead of billing twice. Created
        directly as ISSUED (the sale is confirmed) with revenue recognized only
        when it is later approved.
        """
        existing = await self._repo.get_invoice_by_source_ref(
            INVOICE_SOURCE_SALES_ORDER, order.order_id, order.tenant_id
        )
        if existing is not None:
            return existing

        invoice_lines: list[InvoiceLine] = []
        for line_no, line in enumerate(order.lines, start=1):
            if line.account_id is not None:
                account = await self._repo.get_account_by_id(line.account_id, order.tenant_id)
                if account is None:
                    raise NotFoundError(f"Account {line.account_id} not found")
            else:
                account = await self._repo.get_account_by_code(
                    REVENUE_ACCOUNT_CODE, order.tenant_id
                )
                if account is None:
                    raise NotFoundError(f"Revenue account '{REVENUE_ACCOUNT_CODE}' not found")
            assert account.id is not None
            if line.quantity <= 0:
                raise ValidationError("Invoice line quantity must be positive")
            if line.unit_price < 0:
                raise ValidationError("Invoice line unit price must be non-negative")
            invoice_lines.append(
                InvoiceLine(
                    invoice_id=None,
                    line_no=line_no,
                    description=line.description,
                    account_id=account.id,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    amount=(line.quantity * line.unit_price).quantize(_MONEY_QUANTUM),
                )
            )

        total = sum((line.amount for line in invoice_lines), Decimal("0"))
        number = await self._repo.next_invoice_number(order.tenant_id, order.invoice_date.year)
        invoice = Invoice(
            tenant_id=order.tenant_id,
            invoice_number=number,
            customer_id=order.customer_id,
            invoice_date=order.invoice_date,
            due_date=order.due_date,
            status=InvoiceStatus.ISSUED,
            total=total,
            source=INVOICE_SOURCE_SALES_ORDER,
            source_ref=order.order_id,
            lines=tuple(invoice_lines),
            issued_at=datetime.now(UTC),
        )
        created = await self._repo.create_invoice(invoice)
        await self._announce_invoice_created(order.tenant_id, created, user_id=None)
        return created

    async def get_invoice(self, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
        invoice = await self._repo.get_invoice(invoice_id, tenant_id)
        if invoice is None:
            raise NotFoundError(f"Invoice {invoice_id} not found")
        return invoice

    async def get_invoice_with_customer_name(
        self, tenant_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> tuple[Invoice, str | None]:
        """Return invoice + resolved customer name (avoids N+1 at the router)."""
        invoice = await self.get_invoice(tenant_id, invoice_id)
        name: str | None = None
        if self._customers is not None:
            name = await self._customers.get_customer_name(invoice.customer_id, tenant_id=tenant_id)
        return invoice, name

    async def list_invoices(
        self,
        tenant_id: uuid.UUID,
        *,
        status: InvoiceStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[Invoice]:
        return await self._repo.list_invoices(tenant_id, status=status, offset=offset, limit=limit)

    async def list_invoices_with_customer_names(
        self,
        tenant_id: uuid.UUID,
        *,
        status: InvoiceStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[Invoice], dict[uuid.UUID, str]]:
        """Return invoices + batch-resolved customer names (avoids N+1)."""
        invoices = await self.list_invoices(tenant_id, status=status, offset=offset, limit=limit)
        names: dict[uuid.UUID, str] = {}
        if self._customers is not None and invoices:
            ids = list({inv.customer_id for inv in invoices})
            names = await self._customers.get_customer_names(ids, tenant_id=tenant_id)
        return invoices, names

    async def resolve_source_order_numbers(
        self,
        invoices: Sequence[Invoice],
        tenant_id: uuid.UUID,
    ) -> dict[str, str]:
        """Batch-resolve source_ref -> order_number for sales-order invoices."""
        if self._order_lookup is None:
            return {}
        result: dict[str, str] = {}
        for inv in invoices:
            if inv.source == INVOICE_SOURCE_SALES_ORDER and inv.source_ref:
                try:
                    order_id = uuid.UUID(inv.source_ref)
                except (ValueError, TypeError):
                    continue
                order = await self._order_lookup.get_order(order_id, tenant_id=tenant_id)
                if order is not None and hasattr(order, "order_number"):
                    result[inv.source_ref] = order.order_number
        return result

    async def issue_invoice(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> Invoice:
        invoice = await self.get_invoice(tenant_id, invoice_id)
        if invoice.status != InvoiceStatus.DRAFT:
            raise ConflictError("Only draft invoices can be issued")

        issued = await self._repo.issue_invoice(invoice_id, tenant_id, issued_at=datetime.now(UTC))
        assert issued is not None
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=audit_events.FINANCE_INVOICE_ISSUED,
            target=f"invoice:{invoice_id}",
            details={"invoice_number": issued.invoice_number},
        )
        return issued

    async def approve_invoice(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> Invoice:
        """Approve an issued invoice — revenue recognition (accrual).

        Writes a POSTED accrual entry (DR AR / CR revenue) in the SAME
        transaction as the status flip, stamped ``(source='invoice', source_ref=
        invoice_id)``. The unique lock makes a second approval impossible, and
        the entry is returned in the ``invoice.approved`` event as
        ``revenue_entry_id``.
        """
        invoice = await self.get_invoice(tenant_id, invoice_id)
        if invoice.status != InvoiceStatus.ISSUED:
            raise ConflictError("Only issued invoices can be approved")

        if await self._repo.is_period_closed(invoice.invoice_date, tenant_id):
            raise ConflictError(
                f"Invoice date {invoice.invoice_date.isoformat()} falls in a closed fiscal period"
            )

        ar_account = await self._repo.get_account_by_code(AR_ACCOUNT_CODE, tenant_id)
        if ar_account is None:
            raise NotFoundError(f"AR account '{AR_ACCOUNT_CODE}' not found")
        assert ar_account.id is not None

        revenue_legs: dict[uuid.UUID, Decimal] = {}
        for line in invoice.lines:
            revenue_legs[line.account_id] = revenue_legs.get(line.account_id, Decimal("0")) + (
                line.amount
            )

        accrual = JournalEntry(
            tenant_id=tenant_id,
            entry_date=invoice.invoice_date,
            memo=f"Revenue recognition for invoice {invoice.invoice_number}",
            status=EntryStatus.POSTED,
            source=JOURNAL_SOURCE_INVOICE,
            source_ref=str(invoice_id),
            lines=(
                JournalLine(account_id=ar_account.id, debit=invoice.total),
                *(
                    JournalLine(account_id=account_id, credit=amount)
                    for account_id, amount in sorted(revenue_legs.items())
                ),
            ),
            posted_at=datetime.now(UTC),
            posted_by_user_id=user_id,
        )
        revenue_entry = await self._repo.create_journal_entry(accrual)
        assert revenue_entry.id is not None

        approved = await self._repo.approve_invoice(
            invoice_id, tenant_id, approved_at=datetime.now(UTC)
        )
        assert approved is not None

        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=audit_events.FINANCE_INVOICE_APPROVED,
            target=f"invoice:{invoice_id}",
            details={
                "invoice_number": approved.invoice_number,
                "revenue_entry_id": str(revenue_entry.id),
            },
        )
        self._events.invoice_approved(
            invoice_id=invoice_id,
            invoice_number=approved.invoice_number,
            revenue_entry_id=revenue_entry.id,
            tenant_id=tenant_id,
            correlation_id=self._correlation_id,
        )
        if self._timeline is not None:
            await self._timeline.record_timeline_event(
                tenant_id=tenant_id,
                entity_type=CrmEntityType.CUSTOMER,
                entity_id=invoice.customer_id,
                event_type=CrmTimelineEventType.INVOICE_APPROVED,
                title=f"Invoice {approved.invoice_number} approved",
                payload={
                    "invoice_id": str(invoice_id),
                    "invoice_number": approved.invoice_number,
                    "total": str(invoice.total),
                },
            )
        return approved

    async def void_invoice(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> Invoice:
        invoice = await self.get_invoice(tenant_id, invoice_id)
        if invoice.status not in (InvoiceStatus.DRAFT, InvoiceStatus.ISSUED):
            raise ConflictError("Only draft or issued invoices can be voided")

        voided = await self._repo.void_invoice(invoice_id, tenant_id, voided_at=datetime.now(UTC))
        assert voided is not None
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=audit_events.FINANCE_INVOICE_VOIDED,
            target=f"invoice:{invoice_id}",
            details={"invoice_number": voided.invoice_number},
        )
        return voided

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------

    async def apply_payment(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        invoice_id: uuid.UUID,
        amount: Decimal,
        method: str,
        paid_at: datetime,
    ) -> Payment:
        """Apply a cash receipt to an approved invoice (DR Cash / CR AR).

        Guards: the invoice must be approved, the amount positive, and it must
        not exceed the outstanding balance. When the outstanding balance reaches
        zero the invoice is marked paid in the same transaction. Idempotent per
        ``(source, source_ref)`` — a replayed request can never double-book.
        """
        invoice = await self.get_invoice(tenant_id, invoice_id)
        if invoice.status != InvoiceStatus.APPROVED:
            raise ConflictError("Only approved invoices can receive payments")
        if amount <= 0:
            raise ValidationError("Payment amount must be positive")

        already_paid = await self._repo.sum_payments_for_invoice(invoice_id, tenant_id)
        outstanding = invoice.total - already_paid
        if amount > outstanding:
            raise ValidationError(
                f"Payment {amount} exceeds the outstanding balance of {outstanding}"
            )

        payment = Payment(
            tenant_id=tenant_id,
            payment_number="",  # replaced below
            invoice_id=invoice_id,
            amount=amount,
            method=method,
            paid_at=paid_at,
            status=PaymentStatus.APPLIED,
            source=PAYMENT_SOURCE_MANUAL,
            source_ref=None,
        )
        number = await self._repo.next_payment_number(tenant_id, paid_at.year)
        created = await self._repo.create_payment(replace(payment, payment_number=number))
        assert created.id is not None

        remaining = outstanding - amount
        if remaining == 0:
            await self._repo.mark_invoice_paid(invoice_id, tenant_id)

        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=audit_events.FINANCE_PAYMENT_APPLIED,
            target=f"payment:{created.id}",
            details={
                "payment_number": created.payment_number,
                "invoice_id": str(invoice_id),
                "amount": str(created.amount),
            },
        )
        self._events.payment_applied(
            payment_id=created.id,
            payment_number=created.payment_number,
            invoice_id=invoice_id,
            tenant_id=tenant_id,
            correlation_id=self._correlation_id,
        )
        if self._timeline is not None:
            await self._timeline.record_timeline_event(
                tenant_id=tenant_id,
                entity_type=CrmEntityType.CUSTOMER,
                entity_id=invoice.customer_id,
                event_type=CrmTimelineEventType.PAYMENT_APPLIED,
                title=f"Payment {created.payment_number} applied to {invoice.invoice_number}",
                payload={
                    "payment_id": str(created.id),
                    "payment_number": created.payment_number,
                    "invoice_id": str(invoice_id),
                    "amount": str(created.amount),
                    "method": created.method,
                },
            )
        return created

    async def get_payment(self, tenant_id: uuid.UUID, payment_id: uuid.UUID) -> Payment:
        payment = await self._repo.get_payment(payment_id, tenant_id)
        if payment is None:
            raise NotFoundError(f"Payment {payment_id} not found")
        return payment

    # ------------------------------------------------------------------
    # COGS (cost-of-goods-sold) posting
    # ------------------------------------------------------------------

    async def post_cogs_for_order(
        self,
        *,
        tenant_id: uuid.UUID,
        order_id: str,
        entry_date: date,
        lines: Sequence[CogsLine],
    ) -> None:
        """Post a COGS journal entry after stock consumption (DR COGS / CR Inventory Asset).

        Called by the sales service after ``fulfil_order_lines`` succeeds. The
        entry is created as POSTED in the same transaction — the unique
        ``(source, source_ref)`` lock on journal entries prevents double-posting
        for the same order.
        """
        if not lines:
            return

        total_cogs = Decimal("0")
        for line in lines:
            total_cogs += (line.quantity * line.unit_cost).quantize(_MONEY_QUANTUM)
        if total_cogs <= 0:
            return

        cogs_account = await self._repo.get_account_by_code(COGS_ACCOUNT_CODE, tenant_id)
        if cogs_account is None:
            raise NotFoundError(f"COGS account '{COGS_ACCOUNT_CODE}' not found")
        assert cogs_account.id is not None

        inv_asset_account = await self._repo.get_account_by_code(
            INVENTORY_ASSET_ACCOUNT_CODE, tenant_id
        )
        if inv_asset_account is None:
            raise NotFoundError(
                f"Inventory asset account '{INVENTORY_ASSET_ACCOUNT_CODE}' not found"
            )
        assert inv_asset_account.id is not None

        entry = JournalEntry(
            tenant_id=tenant_id,
            entry_date=entry_date,
            memo=f"COGS for sales order {order_id}",
            status=EntryStatus.POSTED,
            source=JOURNAL_SOURCE_COGS,
            source_ref=order_id,
            lines=(
                JournalLine(account_id=cogs_account.id, debit=total_cogs),
                JournalLine(account_id=inv_asset_account.id, credit=total_cogs),
            ),
            posted_at=datetime.now(UTC),
        )
        created = await self._repo.create_journal_entry(entry)
        assert created.id is not None

        await self._audit.log(
            tenant_id=tenant_id,
            user_id=None,
            action=audit_events.FINANCE_JOURNAL_ENTRY_POSTED,
            target=f"journal_entry:{created.id}",
            details={
                "source": JOURNAL_SOURCE_COGS,
                "source_ref": order_id,
                "total_cogs": str(total_cogs),
            },
        )

    # ------------------------------------------------------------------
    # Payroll accrual bridge (payroll→finance draft JE — HR-AUT-001, Commit 4)
    # ------------------------------------------------------------------

    async def create_payroll_accrual_draft(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        entry_date: date,
        gross: Decimal,
        net: Decimal,
    ) -> PayrollAccrualOutcome:
        """Create the DRAFT accrual JE a paid payroll run books in the Finance inbox.

        Mirrors ``create_manual_entry``/``post_cogs_for_order``: account codes
        are resolved per-tenant and the ``UNIQUE (tenant_id, source,
        source_ref)`` lock (source='payroll', source_ref=run_id) makes a
        replayed handoff idempotent. Unlike COGS this does NOT raise when the
        chart is missing — the missing codes are returned so the payroll
        service records a queryable ``je_bridge_status='pending'`` instead of
        hard-failing mark-paid on an unrelated module's provisioning gap.
        """
        codes = (
            SALARY_EXPENSE_ACCOUNT_CODE,
            ACCRUED_SALARIES_PAYABLE_ACCOUNT_CODE,
            DEDUCTIONS_PAYABLE_ACCOUNT_CODE,
        )
        account_ids: dict[str, uuid.UUID] = {}
        missing: list[str] = []
        for code in codes:
            account = await self._repo.get_account_by_code(code, tenant_id)
            if account is None or not account.is_active:
                missing.append(code)
                continue
            assert account.id is not None
            account_ids[code] = account.id
        if missing:
            return PayrollAccrualOutcome(missing_accounts=tuple(missing))

        deductions = (gross - net).quantize(_MONEY_QUANTUM)
        lines = [
            JournalLine(account_id=account_ids[SALARY_EXPENSE_ACCOUNT_CODE], debit=gross),
            JournalLine(account_id=account_ids[ACCRUED_SALARIES_PAYABLE_ACCOUNT_CODE], credit=net),
        ]
        # A zero-deduction payroll run must not create a 0.00 journal line
        # (the ledger rejects zero amounts); the 2020 leg only exists when
        # gross > net.
        if deductions > 0:
            lines.append(
                JournalLine(
                    account_id=account_ids[DEDUCTIONS_PAYABLE_ACCOUNT_CODE],
                    credit=deductions,
                )
            )
        entry = JournalEntry(
            tenant_id=tenant_id,
            entry_date=entry_date,
            memo=f"Payroll accrual for run {run_id}",
            status=EntryStatus.DRAFT,
            source=JOURNAL_SOURCE_PAYROLL,
            source_ref=str(run_id),
            lines=tuple(lines),
            posted_at=None,
        )
        try:
            created = await self._repo.create_journal_entry(entry)
        except ConflictError:
            # A replayed mark-paid already booked this run — the idempotency
            # lock did its job; the run is reported as booked.
            return PayrollAccrualOutcome(already_booked=True)
        assert created.id is not None
        return PayrollAccrualOutcome(entry_id=created.id)

    # ------------------------------------------------------------------
    # Reports (derived from posted lines — never stored)
    # ------------------------------------------------------------------

    async def trial_balance(self, tenant_id: uuid.UUID, as_of: date) -> TrialBalance:
        return await self._repo.trial_balance(tenant_id, as_of)

    async def profit_and_loss(
        self, tenant_id: uuid.UUID, from_date: date, to_date: date
    ) -> ProfitAndLoss:
        if to_date < from_date:
            raise ValidationError("P&L 'to_date' must be on or after 'from_date'")
        return await self._repo.profit_and_loss(tenant_id, from_date, to_date)

    async def balance_sheet(self, tenant_id: uuid.UUID, as_of: date) -> BalanceSheet:
        return await self._repo.balance_sheet(tenant_id, as_of)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _resolve_invoice_lines(
        self,
        tenant_id: uuid.UUID,
        lines: Sequence[InvoiceLineInput],
    ) -> tuple[tuple[InvoiceLine, ...], Decimal]:
        invoice_lines: list[InvoiceLine] = []
        total = Decimal("0")
        for line_no, line in enumerate(lines, start=1):
            account = await self._repo.get_account_by_code(line.account_code, tenant_id)
            if account is None:
                raise NotFoundError(f"Account with code '{line.account_code}' not found")
            if not account.is_active:
                raise ConflictError(f"Account '{line.account_code}' is deactivated")
            assert account.id is not None
            if line.quantity <= 0:
                raise ValidationError("Invoice line quantity must be positive")
            if line.unit_price < 0:
                raise ValidationError("Invoice line unit price must be non-negative")
            amount = (line.quantity * line.unit_price).quantize(_MONEY_QUANTUM)
            total += amount
            invoice_lines.append(
                InvoiceLine(
                    invoice_id=None,
                    line_no=line_no,
                    description=line.description,
                    account_id=account.id,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    amount=amount,
                )
            )
        return tuple(invoice_lines), total

    async def _announce_invoice_created(
        self, tenant_id: uuid.UUID, invoice: Invoice, *, user_id: uuid.UUID | None
    ) -> None:
        assert invoice.id is not None
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=audit_events.FINANCE_INVOICE_CREATED,
            target=f"invoice:{invoice.id}",
            details={
                "invoice_number": invoice.invoice_number,
                "total": str(invoice.total),
                "source": invoice.source,
            },
        )
        self._events.invoice_created(
            invoice_id=invoice.id,
            invoice_number=invoice.invoice_number,
            tenant_id=tenant_id,
            correlation_id=self._correlation_id,
        )


def _normalize_amount(value: Decimal | None) -> Decimal | None:
    """Return a Decimal rounded to the ledger's 4-decimal scale, or None."""
    if value is None:
        return None
    return value.quantize(_MONEY_QUANTUM)
