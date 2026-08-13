"""Finance repository — DB operations for the money side of the ERP.

The finance module's only DB-touching code. Implements
:class:`core.features.finance.ports.FinanceRepositoryPort` and stays inside the
feature package, so the import-linter rule "Only repositories touch the database
layer" holds while the service (above) depends on the Protocol, never on this
concrete class or on SQLAlchemy.

Guarantees this layer owns:

- **Idempotency**: the ``UNIQUE (tenant_id, source, source_ref)`` constraints on
  journal entries / invoices / payments are the durable lock. Re-creating a
  stamped document raises a unique violation, which is translated to a 409
  ``ConflictError`` here — a replayed handoff can never double-book.
- **Atomic document creation**: header + lines are flushed in one transaction;
  a failed line rolls the whole document back.
- **Numbering**: nextval on the global ``seq_erp_invoice_number`` /
  ``seq_erp_payment_number`` sequences (created by migration 0004) yields
  ``{prefix}-{year}-{seq:05d}`` numbers.
- **Reports are derived, never stored**: trial balance / P&L / balance sheet
  aggregate POSTED journal lines on read, so they can never diverge from the
  ledger.

All probes are tenant-scoped (explicit ``tenant_id`` + RLS), matching the
inventory repository's contract.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import IntegrityError

from core.core.constants import INVOICE_PREFIX, PAYMENT_PREFIX
from core.domain.entities import (
    BalanceSheet,
    BalanceSheetLine,
    ChartOfAccount,
    FiscalPeriod,
    Invoice,
    InvoiceLine,
    JournalEntry,
    JournalLine,
    Payment,
    PnlLine,
    ProfitAndLoss,
    TrialBalance,
    TrialBalanceRow,
)
from core.domain.value_objects import AccountType, EntryStatus, InvoiceStatus, PaymentStatus
from core.features.finance.models.chart_of_account import ErpChartOfAccountModel
from core.features.finance.models.fiscal_period import ErpFiscalPeriodModel
from core.features.finance.models.invoice import ErpInvoiceModel
from core.features.finance.models.invoice_line import ErpInvoiceLineModel
from core.features.finance.models.journal_entry import ErpJournalEntryModel
from core.features.finance.models.journal_line import ErpJournalLineModel
from core.features.finance.models.payment import ErpPaymentModel
from skyrict_common.exceptions import ConflictError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Unique-violation -> ConflictError translation
# ---------------------------------------------------------------------------

_UNIQUE_VIOLATION_MESSAGES: dict[str, str] = {
    "uq_erp_journal_entries_source_ref": "A journal entry for this source document already exists",
    "uq_erp_invoices_tenant_number": "An invoice with this number already exists",
    "uq_erp_invoices_source_ref": "An invoice for this source document already exists",
    "uq_erp_payments_tenant_number": "A payment with this number already exists",
    "uq_erp_payments_source_ref": "A payment for this source document already exists",
    "uq_erp_chart_of_accounts_tenant_code": "An account with this code already exists",
    "uq_erp_fiscal_periods_tenant_name": "A fiscal period with this name already exists",
}
_DEFAULT_CONFLICT_MESSAGE = "The resource conflicts with existing data"


def _conflict_or_reraise(exc: IntegrityError) -> None:
    """Translate a unique violation into a 409 ``ConflictError``, else re-raise.

    Only known UNIQUE constraints are translated; foreign-key / not-null
    violations are programming errors and must surface as 500s.
    """
    orig = getattr(exc, "orig", None)
    constraint = getattr(orig, "constraint_name", None)
    if constraint is None:
        diag = getattr(orig, "diag", None)
        constraint = getattr(diag, "constraint_name", None)
    if constraint in _UNIQUE_VIOLATION_MESSAGES:
        raise ConflictError(_UNIQUE_VIOLATION_MESSAGES[constraint]) from exc
    sqlstate = getattr(orig, "sqlstate", None)
    if sqlstate == "23505":  # unique_violation with an unrecognized constraint
        raise ConflictError(_DEFAULT_CONFLICT_MESSAGE) from exc
    raise exc


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------


def _document_number(prefix: str, year: int, seq: int) -> str:
    return f"{prefix}-{year}-{seq:05d}"


# ---------------------------------------------------------------------------
# ORM <-> entity mapping
# ---------------------------------------------------------------------------


def _account_from_orm(model: ErpChartOfAccountModel) -> ChartOfAccount:
    return ChartOfAccount(
        tenant_id=model.tenant_id,
        code=model.code,
        name=model.name,
        account_type=model.account_type,
        is_active=model.is_active,
        id=model.id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _fiscal_period_from_orm(model: ErpFiscalPeriodModel) -> FiscalPeriod:
    return FiscalPeriod(
        tenant_id=model.tenant_id,
        name=model.name,
        start_date=model.start_date,
        end_date=model.end_date,
        is_closed=model.is_closed,
        id=model.id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _journal_line_from_orm(model: ErpJournalLineModel) -> JournalLine:
    return JournalLine(
        account_id=model.account_id,
        debit=model.debit,
        credit=model.credit,
        currency=model.currency,
        id=model.id,
    )


def _journal_entry_from_orm(
    model: ErpJournalEntryModel, lines: Sequence[JournalLine]
) -> JournalEntry:
    return JournalEntry(
        tenant_id=model.tenant_id,
        entry_date=model.entry_date,
        memo=model.memo,
        status=model.status,
        source=model.source,
        source_ref=model.source_ref,
        lines=tuple(lines),
        id=model.id,
        posted_at=model.posted_at,
        posted_by_user_id=model.posted_by_user_id,
        voided_at=model.voided_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _invoice_line_from_orm(model: ErpInvoiceLineModel) -> InvoiceLine:
    return InvoiceLine(
        invoice_id=model.invoice_id,
        line_no=model.line_no,
        description=model.description,
        account_id=model.account_id,
        quantity=model.quantity,
        unit_price=model.unit_price,
        amount=model.amount,
        id=model.id,
        created_at=model.created_at,
    )


def _invoice_from_orm(model: ErpInvoiceModel, lines: Sequence[InvoiceLine]) -> Invoice:
    return Invoice(
        tenant_id=model.tenant_id,
        invoice_number=model.invoice_number,
        customer_id=model.customer_id,
        invoice_date=model.invoice_date,
        due_date=model.due_date,
        status=model.status,
        total=model.total,
        source=model.source,
        source_ref=model.source_ref,
        lines=tuple(lines),
        id=model.id,
        issued_at=model.issued_at,
        approved_at=model.approved_at,
        voided_at=model.voided_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _payment_from_orm(model: ErpPaymentModel) -> Payment:
    return Payment(
        tenant_id=model.tenant_id,
        payment_number=model.payment_number,
        invoice_id=model.invoice_id,
        amount=model.amount,
        method=model.method,
        paid_at=model.paid_at,
        status=model.status,
        source=model.source,
        source_ref=model.source_ref,
        id=model.id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class FinanceRepository:
    """Concrete SQLAlchemy implementation of :class:`FinanceRepositoryPort`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Chart of accounts
    # ------------------------------------------------------------------

    async def create_account(self, account: ChartOfAccount) -> ChartOfAccount:
        model = ErpChartOfAccountModel(
            tenant_id=account.tenant_id,
            code=account.code,
            name=account.name,
            account_type=account.account_type,
            is_active=account.is_active,
        )
        self.session.add(model)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            _conflict_or_reraise(exc)
        await self.session.refresh(model)
        return _account_from_orm(model)

    async def get_account_by_id(
        self, account_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ChartOfAccount | None:
        stmt = select(ErpChartOfAccountModel).where(
            ErpChartOfAccountModel.tenant_id == tenant_id,
            ErpChartOfAccountModel.id == account_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _account_from_orm(model) if model is not None else None

    async def get_account_by_code(self, code: str, tenant_id: uuid.UUID) -> ChartOfAccount | None:
        stmt = select(ErpChartOfAccountModel).where(
            ErpChartOfAccountModel.tenant_id == tenant_id,
            ErpChartOfAccountModel.code == code,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _account_from_orm(model) if model is not None else None

    async def list_accounts(
        self, tenant_id: uuid.UUID, *, include_inactive: bool = False
    ) -> Sequence[ChartOfAccount]:
        stmt = select(ErpChartOfAccountModel).where(ErpChartOfAccountModel.tenant_id == tenant_id)
        if not include_inactive:
            stmt = stmt.where(ErpChartOfAccountModel.is_active.is_(True))
        stmt = stmt.order_by(ErpChartOfAccountModel.code)
        result = await self.session.execute(stmt)
        return [_account_from_orm(model) for model in result.scalars().all()]

    async def deactivate_account(
        self, account_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ChartOfAccount | None:
        stmt = select(ErpChartOfAccountModel).where(
            ErpChartOfAccountModel.tenant_id == tenant_id,
            ErpChartOfAccountModel.id == account_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        model.is_active = False
        await self.session.flush()
        await self.session.refresh(model)
        return _account_from_orm(model)

    # ------------------------------------------------------------------
    # Journal entries (header + lines, one transaction)
    # ------------------------------------------------------------------

    async def create_journal_entry(self, entry: JournalEntry) -> JournalEntry:
        model = ErpJournalEntryModel(
            tenant_id=entry.tenant_id,
            entry_date=entry.entry_date,
            memo=entry.memo,
            status=entry.status,
            source=entry.source,
            source_ref=entry.source_ref,
        )
        self.session.add(model)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            _conflict_or_reraise(exc)

        line_models = [
            ErpJournalLineModel(
                tenant_id=entry.tenant_id,
                entry_id=model.id,
                account_id=line.account_id,
                debit=line.debit,
                credit=line.credit,
                currency=line.currency,
            )
            for line in entry.lines
        ]
        self.session.add_all(line_models)
        await self.session.flush()
        await self.session.refresh(model)
        return _journal_entry_from_orm(model, [_journal_line_from_orm(lm) for lm in line_models])

    async def get_journal_entry(
        self, entry_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> JournalEntry | None:
        stmt = select(ErpJournalEntryModel).where(
            ErpJournalEntryModel.tenant_id == tenant_id,
            ErpJournalEntryModel.id == entry_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        lines = await self._journal_lines(entry_id, tenant_id)
        return _journal_entry_from_orm(model, lines)

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
        """List entry HEADERS (lines are loaded by ``get_journal_entry``)."""
        stmt = select(ErpJournalEntryModel).where(ErpJournalEntryModel.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(ErpJournalEntryModel.status == status)
        if from_date is not None:
            stmt = stmt.where(ErpJournalEntryModel.entry_date >= from_date)
        if to_date is not None:
            stmt = stmt.where(ErpJournalEntryModel.entry_date <= to_date)
        stmt = (
            stmt.order_by(
                ErpJournalEntryModel.entry_date.desc(), ErpJournalEntryModel.created_at.desc()
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [_journal_entry_from_orm(model, ()) for model in result.scalars().all()]

    async def post_journal_entry(
        self,
        entry_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        posted_by_user_id: uuid.UUID,
        posted_at: datetime,
    ) -> JournalEntry | None:
        model = await self._journal_entry_model(entry_id, tenant_id)
        if model is None:
            return None
        model.status = EntryStatus.POSTED
        model.posted_at = posted_at
        model.posted_by_user_id = posted_by_user_id
        await self.session.flush()
        await self.session.refresh(model)
        lines = await self._journal_lines(entry_id, tenant_id)
        return _journal_entry_from_orm(model, lines)

    async def void_journal_entry(
        self, entry_id: uuid.UUID, tenant_id: uuid.UUID, *, voided_at: datetime
    ) -> JournalEntry | None:
        model = await self._journal_entry_model(entry_id, tenant_id)
        if model is None:
            return None
        model.status = EntryStatus.VOIDED
        model.voided_at = voided_at
        await self.session.flush()
        await self.session.refresh(model)
        lines = await self._journal_lines(entry_id, tenant_id)
        return _journal_entry_from_orm(model, lines)

    async def _journal_entry_model(
        self, entry_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ErpJournalEntryModel | None:
        stmt = select(ErpJournalEntryModel).where(
            ErpJournalEntryModel.tenant_id == tenant_id,
            ErpJournalEntryModel.id == entry_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _journal_lines(
        self, entry_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Sequence[JournalLine]:
        stmt = (
            select(ErpJournalLineModel)
            .where(
                ErpJournalLineModel.tenant_id == tenant_id,
                ErpJournalLineModel.entry_id == entry_id,
            )
            .order_by(ErpJournalLineModel.id)
        )
        result = await self.session.execute(stmt)
        return [_journal_line_from_orm(model) for model in result.scalars().all()]

    # ------------------------------------------------------------------
    # Fiscal periods
    # ------------------------------------------------------------------

    async def create_fiscal_period(self, period: FiscalPeriod) -> FiscalPeriod:
        model = ErpFiscalPeriodModel(
            tenant_id=period.tenant_id,
            name=period.name,
            start_date=period.start_date,
            end_date=period.end_date,
            is_closed=period.is_closed,
        )
        self.session.add(model)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            _conflict_or_reraise(exc)
        await self.session.refresh(model)
        return _fiscal_period_from_orm(model)

    async def list_fiscal_periods(self, tenant_id: uuid.UUID) -> Sequence[FiscalPeriod]:
        stmt = (
            select(ErpFiscalPeriodModel)
            .where(ErpFiscalPeriodModel.tenant_id == tenant_id)
            .order_by(ErpFiscalPeriodModel.start_date)
        )
        result = await self.session.execute(stmt)
        return [_fiscal_period_from_orm(model) for model in result.scalars().all()]

    async def close_fiscal_period(
        self, period_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> FiscalPeriod | None:
        stmt = select(ErpFiscalPeriodModel).where(
            ErpFiscalPeriodModel.tenant_id == tenant_id,
            ErpFiscalPeriodModel.id == period_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        model.is_closed = True
        await self.session.flush()
        await self.session.refresh(model)
        return _fiscal_period_from_orm(model)

    async def is_period_closed(self, entry_date: date, tenant_id: uuid.UUID) -> bool:
        stmt = (
            select(ErpFiscalPeriodModel.id)
            .where(
                ErpFiscalPeriodModel.tenant_id == tenant_id,
                ErpFiscalPeriodModel.start_date <= entry_date,
                ErpFiscalPeriodModel.end_date >= entry_date,
                ErpFiscalPeriodModel.is_closed.is_(True),
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).first() is not None

    # ------------------------------------------------------------------
    # Invoices (header + lines)
    # ------------------------------------------------------------------

    async def create_invoice(self, invoice: Invoice) -> Invoice:
        model = ErpInvoiceModel(
            tenant_id=invoice.tenant_id,
            invoice_number=invoice.invoice_number,
            customer_id=invoice.customer_id,
            invoice_date=invoice.invoice_date,
            due_date=invoice.due_date,
            status=invoice.status,
            total=invoice.total,
            source=invoice.source,
            source_ref=invoice.source_ref,
        )
        self.session.add(model)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            _conflict_or_reraise(exc)

        line_models = [
            ErpInvoiceLineModel(
                tenant_id=invoice.tenant_id,
                invoice_id=model.id,
                line_no=line.line_no,
                description=line.description,
                account_id=line.account_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
                amount=line.amount,
            )
            for line in invoice.lines
        ]
        self.session.add_all(line_models)
        await self.session.flush()
        await self.session.refresh(model)
        for line_model in line_models:
            await self.session.refresh(line_model)
        return _invoice_from_orm(model, [_invoice_line_from_orm(lm) for lm in line_models])

    async def get_invoice(self, invoice_id: uuid.UUID, tenant_id: uuid.UUID) -> Invoice | None:
        stmt = select(ErpInvoiceModel).where(
            ErpInvoiceModel.tenant_id == tenant_id,
            ErpInvoiceModel.id == invoice_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        lines = await self._invoice_lines(invoice_id, tenant_id)
        return _invoice_from_orm(model, lines)

    async def get_invoice_by_source_ref(
        self, source: str, source_ref: str, tenant_id: uuid.UUID
    ) -> Invoice | None:
        stmt = select(ErpInvoiceModel).where(
            ErpInvoiceModel.tenant_id == tenant_id,
            ErpInvoiceModel.source == source,
            ErpInvoiceModel.source_ref == source_ref,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        lines = await self._invoice_lines(model.id, tenant_id)
        return _invoice_from_orm(model, lines)

    async def list_invoices(
        self,
        tenant_id: uuid.UUID,
        *,
        status: InvoiceStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[Invoice]:
        """List invoice HEADERS (lines are loaded by ``get_invoice``)."""
        stmt = select(ErpInvoiceModel).where(ErpInvoiceModel.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(ErpInvoiceModel.status == status)
        stmt = (
            stmt.order_by(ErpInvoiceModel.invoice_date.desc(), ErpInvoiceModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [_invoice_from_orm(model, ()) for model in result.scalars().all()]

    async def issue_invoice(
        self, invoice_id: uuid.UUID, tenant_id: uuid.UUID, *, issued_at: datetime
    ) -> Invoice | None:
        model = await self._invoice_model(invoice_id, tenant_id)
        if model is None:
            return None
        model.status = InvoiceStatus.ISSUED
        model.issued_at = issued_at
        await self.session.flush()
        await self.session.refresh(model)
        lines = await self._invoice_lines(invoice_id, tenant_id)
        return _invoice_from_orm(model, lines)

    async def approve_invoice(
        self, invoice_id: uuid.UUID, tenant_id: uuid.UUID, *, approved_at: datetime
    ) -> Invoice | None:
        model = await self._invoice_model(invoice_id, tenant_id)
        if model is None:
            return None
        model.status = InvoiceStatus.APPROVED
        model.approved_at = approved_at
        await self.session.flush()
        await self.session.refresh(model)
        lines = await self._invoice_lines(invoice_id, tenant_id)
        return _invoice_from_orm(model, lines)

    async def void_invoice(
        self, invoice_id: uuid.UUID, tenant_id: uuid.UUID, *, voided_at: datetime
    ) -> Invoice | None:
        model = await self._invoice_model(invoice_id, tenant_id)
        if model is None:
            return None
        model.status = InvoiceStatus.VOIDED
        model.voided_at = voided_at
        await self.session.flush()
        await self.session.refresh(model)
        lines = await self._invoice_lines(invoice_id, tenant_id)
        return _invoice_from_orm(model, lines)

    async def _invoice_model(
        self, invoice_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ErpInvoiceModel | None:
        stmt = select(ErpInvoiceModel).where(
            ErpInvoiceModel.tenant_id == tenant_id,
            ErpInvoiceModel.id == invoice_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _invoice_lines(
        self, invoice_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Sequence[InvoiceLine]:
        stmt = (
            select(ErpInvoiceLineModel)
            .where(
                ErpInvoiceLineModel.tenant_id == tenant_id,
                ErpInvoiceLineModel.invoice_id == invoice_id,
            )
            .order_by(ErpInvoiceLineModel.line_no)
        )
        result = await self.session.execute(stmt)
        return [_invoice_line_from_orm(model) for model in result.scalars().all()]

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------

    async def create_payment(self, payment: Payment) -> Payment:
        model = ErpPaymentModel(
            tenant_id=payment.tenant_id,
            payment_number=payment.payment_number,
            invoice_id=payment.invoice_id,
            amount=payment.amount,
            method=payment.method,
            paid_at=payment.paid_at,
            status=payment.status,
            source=payment.source,
            source_ref=payment.source_ref,
        )
        self.session.add(model)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            _conflict_or_reraise(exc)
        await self.session.refresh(model)
        return _payment_from_orm(model)

    async def get_payment(self, payment_id: uuid.UUID, tenant_id: uuid.UUID) -> Payment | None:
        stmt = select(ErpPaymentModel).where(
            ErpPaymentModel.tenant_id == tenant_id,
            ErpPaymentModel.id == payment_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _payment_from_orm(model) if model is not None else None

    async def get_payment_by_source_ref(
        self, source: str, source_ref: str, tenant_id: uuid.UUID
    ) -> Payment | None:
        stmt = select(ErpPaymentModel).where(
            ErpPaymentModel.tenant_id == tenant_id,
            ErpPaymentModel.source == source,
            ErpPaymentModel.source_ref == source_ref,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _payment_from_orm(model) if model is not None else None

    async def sum_payments_for_invoice(
        self, invoice_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Decimal:
        stmt = select(func.coalesce(func.sum(ErpPaymentModel.amount), 0)).where(
            ErpPaymentModel.tenant_id == tenant_id,
            ErpPaymentModel.invoice_id == invoice_id,
            ErpPaymentModel.status == PaymentStatus.APPLIED,
        )
        return Decimal((await self.session.execute(stmt)).scalar_one())

    # ------------------------------------------------------------------
    # Numbering (nextval on the migration-0004 sequences)
    # ------------------------------------------------------------------

    async def next_invoice_number(self, tenant_id: uuid.UUID, year: int) -> str:
        stmt = select(func.nextval(text("seq_erp_invoice_number")))
        seq = int((await self.session.execute(stmt)).scalar_one())
        return _document_number(INVOICE_PREFIX, year, seq)

    async def next_payment_number(self, tenant_id: uuid.UUID, year: int) -> str:
        stmt = select(func.nextval(text("seq_erp_payment_number")))
        seq = int((await self.session.execute(stmt)).scalar_one())
        return _document_number(PAYMENT_PREFIX, year, seq)

    # ------------------------------------------------------------------
    # Reports (aggregate POSTED lines on read — never stored)
    # ------------------------------------------------------------------

    async def trial_balance(self, tenant_id: uuid.UUID, as_of: date) -> TrialBalance:
        stmt = (
            select(
                ErpJournalLineModel.account_id.label("account_id"),
                ErpChartOfAccountModel.code.label("code"),
                ErpChartOfAccountModel.name.label("name"),
                ErpChartOfAccountModel.account_type.label("account_type"),
                func.coalesce(func.sum(ErpJournalLineModel.debit), 0).label("debit"),
                func.coalesce(func.sum(ErpJournalLineModel.credit), 0).label("credit"),
            )
            .join(
                ErpJournalEntryModel,
                and_(
                    ErpJournalLineModel.tenant_id == ErpJournalEntryModel.tenant_id,
                    ErpJournalLineModel.entry_id == ErpJournalEntryModel.id,
                ),
            )
            .join(
                ErpChartOfAccountModel,
                and_(
                    ErpJournalLineModel.tenant_id == ErpChartOfAccountModel.tenant_id,
                    ErpJournalLineModel.account_id == ErpChartOfAccountModel.id,
                ),
            )
            .where(
                ErpJournalEntryModel.tenant_id == tenant_id,
                ErpJournalEntryModel.status == EntryStatus.POSTED,
                ErpJournalEntryModel.entry_date <= as_of,
            )
            .group_by(
                ErpJournalLineModel.account_id,
                ErpChartOfAccountModel.code,
                ErpChartOfAccountModel.name,
                ErpChartOfAccountModel.account_type,
            )
            .order_by(ErpChartOfAccountModel.code)
        )
        rows = (await self.session.execute(stmt)).all()
        report_rows = tuple(
            TrialBalanceRow(
                account_id=row.account_id,
                code=row.code,
                name=row.name,
                account_type=row.account_type,
                debit=Decimal(row.debit),
                credit=Decimal(row.credit),
            )
            for row in rows
        )
        total_debit = sum((r.debit for r in report_rows), Decimal("0"))
        total_credit = sum((r.credit for r in report_rows), Decimal("0"))
        return TrialBalance(
            as_of=as_of, rows=report_rows, total_debit=total_debit, total_credit=total_credit
        )

    async def profit_and_loss(
        self, tenant_id: uuid.UUID, from_date: date, to_date: date
    ) -> ProfitAndLoss:
        stmt = (
            select(
                ErpJournalLineModel.account_id.label("account_id"),
                ErpChartOfAccountModel.code.label("code"),
                ErpChartOfAccountModel.name.label("name"),
                ErpChartOfAccountModel.account_type.label("account_type"),
                func.coalesce(func.sum(ErpJournalLineModel.debit), 0).label("debit"),
                func.coalesce(func.sum(ErpJournalLineModel.credit), 0).label("credit"),
            )
            .join(
                ErpJournalEntryModel,
                and_(
                    ErpJournalLineModel.tenant_id == ErpJournalEntryModel.tenant_id,
                    ErpJournalLineModel.entry_id == ErpJournalEntryModel.id,
                ),
            )
            .join(
                ErpChartOfAccountModel,
                and_(
                    ErpJournalLineModel.tenant_id == ErpChartOfAccountModel.tenant_id,
                    ErpJournalLineModel.account_id == ErpChartOfAccountModel.id,
                ),
            )
            .where(
                ErpJournalEntryModel.tenant_id == tenant_id,
                ErpJournalEntryModel.status == EntryStatus.POSTED,
                ErpJournalEntryModel.entry_date >= from_date,
                ErpJournalEntryModel.entry_date <= to_date,
                ErpChartOfAccountModel.account_type.in_([AccountType.REVENUE, AccountType.EXPENSE]),
            )
            .group_by(
                ErpJournalLineModel.account_id,
                ErpChartOfAccountModel.code,
                ErpChartOfAccountModel.name,
                ErpChartOfAccountModel.account_type,
            )
            .order_by(ErpChartOfAccountModel.code)
        )
        rows = (await self.session.execute(stmt)).all()

        revenue: list[PnlLine] = []
        expenses: list[PnlLine] = []
        for row in rows:
            if row.account_type == AccountType.REVENUE:
                amount = Decimal(row.credit) - Decimal(row.debit)
                revenue.append(PnlLine(row.account_id, row.code, row.name, amount))
            else:
                amount = Decimal(row.debit) - Decimal(row.credit)
                expenses.append(PnlLine(row.account_id, row.code, row.name, amount))

        total_revenue = sum((line.amount for line in revenue), Decimal("0"))
        total_expenses = sum((line.amount for line in expenses), Decimal("0"))
        return ProfitAndLoss(
            from_date=from_date,
            to_date=to_date,
            revenue=tuple(revenue),
            expenses=tuple(expenses),
            total_revenue=total_revenue,
            total_expenses=total_expenses,
            net_income=total_revenue - total_expenses,
        )

    async def balance_sheet(self, tenant_id: uuid.UUID, as_of: date) -> BalanceSheet:
        stmt = (
            select(
                ErpJournalLineModel.account_id.label("account_id"),
                ErpChartOfAccountModel.code.label("code"),
                ErpChartOfAccountModel.name.label("name"),
                ErpChartOfAccountModel.account_type.label("account_type"),
                func.coalesce(func.sum(ErpJournalLineModel.debit), 0).label("debit"),
                func.coalesce(func.sum(ErpJournalLineModel.credit), 0).label("credit"),
            )
            .join(
                ErpJournalEntryModel,
                and_(
                    ErpJournalLineModel.tenant_id == ErpJournalEntryModel.tenant_id,
                    ErpJournalLineModel.entry_id == ErpJournalEntryModel.id,
                ),
            )
            .join(
                ErpChartOfAccountModel,
                and_(
                    ErpJournalLineModel.tenant_id == ErpChartOfAccountModel.tenant_id,
                    ErpJournalLineModel.account_id == ErpChartOfAccountModel.id,
                ),
            )
            .where(
                ErpJournalEntryModel.tenant_id == tenant_id,
                ErpJournalEntryModel.status == EntryStatus.POSTED,
                ErpJournalEntryModel.entry_date <= as_of,
                ErpChartOfAccountModel.account_type.in_(
                    [AccountType.ASSET, AccountType.LIABILITY, AccountType.EQUITY]
                ),
            )
            .group_by(
                ErpJournalLineModel.account_id,
                ErpChartOfAccountModel.code,
                ErpChartOfAccountModel.name,
                ErpChartOfAccountModel.account_type,
            )
            .order_by(ErpChartOfAccountModel.code)
        )
        rows = (await self.session.execute(stmt)).all()

        assets: list[BalanceSheetLine] = []
        liabilities: list[BalanceSheetLine] = []
        equity: list[BalanceSheetLine] = []
        for row in rows:
            debit = Decimal(row.debit)
            credit = Decimal(row.credit)
            if row.account_type == AccountType.ASSET:
                balance = debit - credit
                assets.append(BalanceSheetLine(row.account_id, row.code, row.name, balance))
            elif row.account_type == AccountType.LIABILITY:
                balance = credit - debit
                liabilities.append(BalanceSheetLine(row.account_id, row.code, row.name, balance))
            else:
                balance = credit - debit
                equity.append(BalanceSheetLine(row.account_id, row.code, row.name, balance))

        return BalanceSheet(
            as_of=as_of,
            assets=tuple(assets),
            liabilities=tuple(liabilities),
            equity=tuple(equity),
            total_assets=sum((line.balance for line in assets), Decimal("0")),
            total_liabilities=sum((line.balance for line in liabilities), Decimal("0")),
            total_equity=sum((line.balance for line in equity), Decimal("0")),
        )
