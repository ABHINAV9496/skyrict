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

import re
import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import IntegrityError

from core.core.constants import INVOICE_PREFIX, PAYMENT_PREFIX
from core.domain.entities import (
    AccountCodeSuggestion,
    AiFinanceAnomaly,
    AiFinanceSuggestion,
    ArAging,
    ArAgingBucket,
    BalanceSheet,
    BalanceSheetLine,
    CashflowPosition,
    CashflowProjection,
    ChartOfAccount,
    CloseChecklist,
    CloseChecklistItem,
    ComparativePnl,
    ComparativePnlRow,
    DuplicateCandidate,
    DuplicateGroup,
    FiscalPeriod,
    HealthComponent,
    HealthScore,
    Invoice,
    InvoiceLine,
    JournalEntry,
    JournalLine,
    Payment,
    PnlLine,
    ProfitAndLoss,
    TenantSetting,
    TrialBalance,
    TrialBalanceRow,
    WorkingCapitalAlert,
)
from core.domain.value_objects import AccountType, EntryStatus, InvoiceStatus, PaymentStatus
from core.features.finance.models.ai_finance_anomaly import AiFinanceAnomalyModel
from core.features.finance.models.ai_finance_suggestion import AiFinanceSuggestionModel
from core.features.finance.models.chart_of_account import ErpChartOfAccountModel
from core.features.finance.models.fiscal_period import ErpFiscalPeriodModel
from core.features.finance.models.invoice import ErpInvoiceModel
from core.features.finance.models.invoice_line import ErpInvoiceLineModel
from core.features.finance.models.journal_entry import ErpJournalEntryModel
from core.features.finance.models.journal_line import ErpJournalLineModel
from core.features.finance.models.payment import ErpPaymentModel
from core.features.finance.models.tenant_setting import ErpTenantSettingModel
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
        reversal_entry_id=model.reversal_entry_id,
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


def _tenant_setting_from_orm(model: ErpTenantSettingModel) -> TenantSetting:
    return TenantSetting(
        tenant_id=model.tenant_id,
        key=model.key,
        value=model.value,
        id=model.id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _ai_suggestion_from_orm(model: AiFinanceSuggestionModel) -> AiFinanceSuggestion:
    return AiFinanceSuggestion(
        tenant_id=model.tenant_id,
        description=model.description,
        suggested_code=model.suggested_code,
        suggested_name=model.suggested_name,
        confidence=model.confidence,
        status=model.status,
        id=model.id,
        created_at=model.created_at,
    )


def _ai_anomaly_from_orm(model: AiFinanceAnomalyModel) -> AiFinanceAnomaly:
    return AiFinanceAnomaly(
        tenant_id=model.tenant_id,
        entity_type=model.entity_type,
        entity_id=model.entity_id,
        anomaly_type=model.anomaly_type,
        severity=model.severity,
        description=model.description,
        status=model.status,
        id=model.id,
        detected_at=model.detected_at,
        reviewed_at=model.reviewed_at,
    )


def _sum_type_balance(lines: Sequence[BalanceSheetLine], account_type: AccountType) -> Decimal:
    return sum((line.balance for line in lines if line.account_type == account_type), Decimal("0"))


def _end_of_month(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1) - timedelta(days=1)
    return date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)


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
            posted_at=entry.posted_at,
            posted_by_user_id=entry.posted_by_user_id,
            voided_at=entry.voided_at,
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
        entry_models = list(result.scalars().all())
        if not entry_models:
            return []
        entry_ids = [m.id for m in entry_models]
        lines_stmt = (
            select(ErpJournalLineModel)
            .where(
                ErpJournalLineModel.tenant_id == tenant_id,
                ErpJournalLineModel.entry_id.in_(entry_ids),
            )
            .order_by(ErpJournalLineModel.entry_id, ErpJournalLineModel.id)
        )
        lines_result = await self.session.execute(lines_stmt)
        lines_by_entry: dict[uuid.UUID, list[JournalLine]] = {}
        for lm in lines_result.scalars().all():
            lines_by_entry.setdefault(lm.entry_id, []).append(_journal_line_from_orm(lm))
        return [
            _journal_entry_from_orm(model, lines_by_entry.get(model.id, ()))
            for model in entry_models
        ]

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

    async def mark_invoice_paid(
        self, invoice_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Invoice | None:
        model = await self._invoice_model(invoice_id, tenant_id)
        if model is None:
            return None
        model.status = InvoiceStatus.PAID
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
        stmt = select(text("nextval('seq_erp_invoice_number')"))
        seq = int((await self.session.execute(stmt)).scalar_one())
        return _document_number(INVOICE_PREFIX, year, seq)

    async def next_payment_number(self, tenant_id: uuid.UUID, year: int) -> str:
        stmt = select(text("nextval('seq_erp_payment_number')"))
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
                assets.append(
                    BalanceSheetLine(row.account_id, row.code, row.name, balance, row.account_type)
                )
            elif row.account_type == AccountType.LIABILITY:
                balance = credit - debit
                liabilities.append(
                    BalanceSheetLine(row.account_id, row.code, row.name, balance, row.account_type)
                )
            else:
                balance = credit - debit
                equity.append(
                    BalanceSheetLine(row.account_id, row.code, row.name, balance, row.account_type)
                )

        return BalanceSheet(
            as_of=as_of,
            assets=tuple(assets),
            liabilities=tuple(liabilities),
            equity=tuple(equity),
            total_assets=sum((line.balance for line in assets), Decimal("0")),
            total_liabilities=sum((line.balance for line in liabilities), Decimal("0")),
            total_equity=sum((line.balance for line in equity), Decimal("0")),
        )

    async def ar_aging(self, tenant_id: uuid.UUID, as_of: date) -> ArAging:
        """Aging of outstanding receivables on ``as_of``.

        Outstanding AR is derived from issued/approved (unpaid) invoices; paid
        and voided invoices are excluded. Buckets are computed from ``due_date``
        relative to ``as_of``:
        current (due on/after as_of), 1-30, 31-60, 61-90, over 90 days past due.
        """
        buckets: dict[str, tuple[int, Decimal]] = {}
        bucket_order: list[str] = []
        total_ar = Decimal("0")

        stmt = select(ErpInvoiceModel).where(
            ErpInvoiceModel.tenant_id == tenant_id,
            ErpInvoiceModel.status.in_([InvoiceStatus.ISSUED, InvoiceStatus.APPROVED]),
        )
        result = await self.session.execute(stmt)
        for model in result.scalars().all():
            age_days = (as_of - model.due_date).days
            if age_days <= 0:
                key = "current"
            elif age_days <= 30:
                key = "1_30"
            elif age_days <= 60:
                key = "31_60"
            elif age_days <= 90:
                key = "61_90"
            else:
                key = "over_90"
            if key not in buckets:
                buckets[key] = (0, Decimal("0"))
                bucket_order.append(key)
            count, amount = buckets[key]
            buckets[key] = (count + 1, amount + Decimal(model.total))

        total_ar = sum((amount for _, amount in buckets.values()), Decimal("0"))
        quantum = Decimal("0.0001")
        ar_buckets: list[ArAgingBucket] = []
        for key in bucket_order:
            count, amount = buckets[key]
            share = amount / total_ar if total_ar else Decimal("0")
            share = share.quantize(quantum)
            ar_buckets.append(ArAgingBucket(bucket=key, count=count, amount=amount, share=share))

        return ArAging(
            as_of=as_of,
            total_ar=total_ar,
            buckets=tuple(ar_buckets),
        )

    # ------------------------------------------------------------------
    # Finance automation (SKY-56/SKY-64)
    # ------------------------------------------------------------------

    async def _get_period(
        self, tenant_id: uuid.UUID, period_id: uuid.UUID
    ) -> ErpFiscalPeriodModel | None:
        stmt = select(ErpFiscalPeriodModel).where(
            ErpFiscalPeriodModel.tenant_id == tenant_id,
            ErpFiscalPeriodModel.id == period_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def close_checklist(self, tenant_id: uuid.UUID, period_id: uuid.UUID) -> CloseChecklist:
        period = await self._get_period(tenant_id, period_id)
        if period is None:
            return CloseChecklist(period_id=period_id, period_name="", items=(), ready=False)
        items: list[CloseChecklistItem] = []

        periods = await self.list_fiscal_periods(tenant_id)
        items.append(
            CloseChecklistItem(
                label="Previous period closed",
                status="ok"
                if all(p.is_closed for p in periods if p.id != period.id)
                else "warning",
                detail="All earlier periods must be closed before this one",
            )
        )

        entry_count = await self._count_posted_entries_in_period(tenant_id, period)
        items.append(
            CloseChecklistItem(
                label="Journal entries posted",
                status="ok" if entry_count and entry_count >= 8 else "missing",
                detail=f"{entry_count} posted entries in period",
            )
        )

        trial = await self.trial_balance(tenant_id, period.end_date)
        balanced = trial.total_debit == trial.total_credit
        items.append(
            CloseChecklistItem(
                label="Trial balance balanced",
                status="ok" if balanced else "missing",
                detail=(
                    f"Debit {trial.total_debit} = Credit {trial.total_credit}"
                    if balanced
                    else f"Debit {trial.total_debit} != Credit {trial.total_credit}"
                ),
            )
        )

        aging = await self.ar_aging(tenant_id, period.end_date)
        over_90 = next((b for b in aging.buckets if b.bucket == "over_90"), None)
        unreconciled = (over_90.amount if over_90 else Decimal("0")) > Decimal("0")
        items.append(
            CloseChecklistItem(
                label="No aged receivables",
                status="warning" if unreconciled else "ok",
                detail="Outstanding AR that is more than 90 days past due"
                if unreconciled
                else "No aging AR in the over-90 bucket",
            )
        )

        all_ok = all(item.status == "ok" for item in items)
        return CloseChecklist(
            period_id=period.id,
            period_name=period.name,
            items=tuple(items),
            ready=all_ok,
        )

    async def _count_posted_entries_in_period(
        self, tenant_id: uuid.UUID, period: ErpFiscalPeriodModel
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(ErpJournalEntryModel)
            .where(
                ErpJournalEntryModel.tenant_id == tenant_id,
                ErpJournalEntryModel.status == EntryStatus.POSTED,
                ErpJournalEntryModel.entry_date >= period.start_date,
                ErpJournalEntryModel.entry_date <= period.end_date,
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def duplicates(self, tenant_id: uuid.UUID) -> Sequence[DuplicateGroup]:
        stmt = (
            select(
                ErpJournalEntryModel.memo.label("memo"),
                ErpJournalEntryModel.entry_date.label("entry_date"),
                func.count().label("cnt"),
            )
            .where(
                ErpJournalEntryModel.tenant_id == tenant_id,
                ErpJournalEntryModel.status == EntryStatus.POSTED,
                ErpJournalEntryModel.memo.isnot(None),
            )
            .group_by(ErpJournalEntryModel.memo, ErpJournalEntryModel.entry_date)
            .having(func.count() > 1)
        )
        rows = (await self.session.execute(stmt)).all()

        groups: list[DuplicateGroup] = []
        for row in rows:
            entry_stmt = (
                select(ErpJournalEntryModel)
                .where(
                    ErpJournalEntryModel.tenant_id == tenant_id,
                    ErpJournalEntryModel.status == EntryStatus.POSTED,
                    ErpJournalEntryModel.memo == row.memo,
                    ErpJournalEntryModel.entry_date == row.entry_date,
                )
                .order_by(ErpJournalEntryModel.created_at)
            )
            entries = (await self.session.execute(entry_stmt)).scalars().all()
            groups.append(
                DuplicateGroup(
                    key=f"{row.memo}|{row.entry_date.isoformat()}",
                    reason=f"{len(entries)} entries share memo '{row.memo}' on {row.entry_date}",
                    entries=tuple(
                        DuplicateCandidate(
                            entry_id=e.id,
                            entry_date=e.entry_date,
                            memo=e.memo,
                            source_ref=e.source_ref,
                        )
                        for e in entries
                    ),
                )
            )
        return tuple(groups)

    async def suggest_account_code(
        self, tenant_id: uuid.UUID, description: str
    ) -> AccountCodeSuggestion:
        """Deterministic keyword fallback — best-effort, honest no-match.

        Returns an empty suggestion (no code/name, confidence 0) when no
        account scores above zero, so the UI never shows a misleading
        "first account" guess. AI-backed suggestions are produced upstream in
        :class:`FinanceService`/the router when ai-agent is reachable.
        """
        accounts = await self.list_accounts(tenant_id)
        if not accounts:
            return AccountCodeSuggestion(
                description=description,
                suggested_code="",
                suggested_name="",
                confidence=Decimal("0"),
            )
        text_lower = description.lower()
        best = None
        best_score = 0
        for account in accounts:
            score = self._keyword_score(text_lower, account.name.lower())
            if score > best_score:
                best = account
                best_score = score

        amount, side = self._extract_amount_from_description(text_lower)

        if best is None:
            return AccountCodeSuggestion(
                description=description,
                suggested_code="",
                suggested_name="",
                confidence=Decimal("0"),
                amount=amount,
                side=side,
            )
        return AccountCodeSuggestion(
            description=description,
            suggested_code=best.code,
            suggested_name=best.name,
            confidence=Decimal(str(best_score)),
            amount=amount,
            side=side,
        )

    @staticmethod
    def _keyword_score(haystack: str, account_name: str) -> int:
        keywords = {
            "rent": 3,
            "salary": 3,
            "wage": 3,
            "utilities": 3,
            "electric": 3,
            "insurance": 3,
            "travel": 3,
            "office": 2,
            "supplies": 2,
        }
        score = 0
        for word, weight in keywords.items():
            if word in haystack and word in account_name:
                score += weight
        return score

    _AMOUNT_RE = re.compile(
        r"(?:(?:usd|eur|gbp|\$)\s*)?"
        r"(\d{1,3}(?:[,\.]\d{3})*(?:\.\d{1,2})?)"
        r"\s*(?:usd|eur|gbp)?(?!\w)",
        re.IGNORECASE,
    )
    _DEBIT_HINTS = frozenset(
        {
            "paid",
            "expense",
            "cost",
            "purchase",
            "rent",
            "salary",
            "wage",
            "utilities",
            "insurance",
            "travel",
            "supplies",
            "office",
            "electric",
            "debit",
        }
    )
    _CREDIT_HINTS = frozenset(
        {"received", "revenue", "income", "credit", "refund", "interest earned"}
    )

    @staticmethod
    def _extract_amount_from_description(text: str) -> tuple[Decimal | None, str]:
        """Best-effort amount + side extraction from free-text description.

        Returns ``(amount, side)`` where *side* is ``"debit"`` or ``"credit"``.
        If no amount pattern is found, returns ``(None, "debit")``.
        """
        match = FinanceRepository._AMOUNT_RE.search(text)
        if not match:
            return None, "debit"
        raw = match.group(1).replace(",", "")
        try:
            amount = Decimal(raw)
        except Exception:
            return None, "debit"
        if amount <= 0:
            return None, "debit"
        words = set(text.split())
        side = "credit" if words & FinanceRepository._CREDIT_HINTS else "debit"
        return amount, side

    async def working_capital_alert(self, tenant_id: uuid.UUID, as_of: date) -> WorkingCapitalAlert:
        threshold = Decimal("1.5")
        balance = await self.balance_sheet(tenant_id, as_of)
        # ponytail: every ASSET is treated as current and every LIABILITY as
        # current — no current/non-current split exists on the chart yet. Add
        # a sub-classification on the COA if the ratio needs to be precise.
        current_assets = sum((line.balance for line in balance.assets), Decimal("0"))
        current_liabilities = sum((line.balance for line in balance.liabilities), Decimal("0"))
        ratio = current_assets / current_liabilities if current_liabilities else Decimal("0")
        quantum = Decimal("0.01")
        ratio = ratio.quantize(quantum)
        return WorkingCapitalAlert(
            ratio=ratio,
            threshold=threshold,
            current_assets=current_assets,
            current_liabilities=current_liabilities,
            alert=current_liabilities > 0 and ratio < threshold,
        )

    async def health_score(self, tenant_id: uuid.UUID, as_of: date) -> HealthScore:
        quantum = Decimal("0.01")
        wc = await self.working_capital_alert(tenant_id, as_of)
        wc_score = Decimal("100") if not wc.alert else Decimal("50")

        aging = await self.ar_aging(tenant_id, as_of)
        over_90 = next((b for b in aging.buckets if b.bucket == "over_90"), None)
        over_90_amount = over_90.amount if over_90 else Decimal("0")
        ar_ok = over_90_amount <= (aging.total_ar * Decimal("0.2"))
        ar_score = Decimal("100") if ar_ok else Decimal("60")

        entries = await self.list_journal_entries(tenant_id, limit=100)
        drafts = sum(1 for e in entries if e.status == EntryStatus.DRAFT)
        drafts_score = max(Decimal("100") - Decimal(drafts) * Decimal("10"), Decimal("0"))

        components = (
            HealthComponent("working_capital", wc_score, Decimal("0.4")),
            HealthComponent("receivables_aging", ar_score, Decimal("0.3")),
            HealthComponent("journal_cleanliness", drafts_score, Decimal("0.3")),
        )
        overall = sum((c.score * c.weight for c in components), Decimal("0")).quantize(quantum)
        return HealthScore(overall=overall, components=components)

    async def cashflow_projection(self, tenant_id: uuid.UUID, as_of: date) -> CashflowProjection:
        months: list[CashflowPosition] = []
        opening = Decimal("0")
        for i in range(6):
            month_start = date(
                as_of.year + (as_of.month + i - 1) // 12, (as_of.month + i - 1) % 12 + 1, 1
            )
            inflows = await self._monthly_outstanding(tenant_id, month_start, is_inflow=True)
            outflows = await self._monthly_outstanding(tenant_id, month_start, is_inflow=False)
            closing = opening + inflows - outflows
            months.append(
                CashflowPosition(
                    month=month_start.strftime("%Y-%m"),
                    opening=opening,
                    inflows=inflows,
                    outflows=outflows,
                    closing=closing,
                )
            )
            opening = closing
        return CashflowProjection(positions=tuple(months))

    async def _monthly_outstanding(
        self, tenant_id: uuid.UUID, month_start: date, *, is_inflow: bool
    ) -> Decimal:
        month_end = _end_of_month(month_start)
        statuses = (
            [InvoiceStatus.ISSUED, InvoiceStatus.APPROVED] if is_inflow else [InvoiceStatus.ISSUED]
        )
        stmt = select(func.coalesce(func.sum(ErpInvoiceModel.total), 0)).where(
            ErpInvoiceModel.tenant_id == tenant_id,
            ErpInvoiceModel.status.in_(statuses),
            ErpInvoiceModel.due_date >= month_start,
            ErpInvoiceModel.due_date <= month_end,
        )
        return Decimal((await self.session.execute(stmt)).scalar_one())

    async def anomalies(self, tenant_id: uuid.UUID) -> Sequence[AiFinanceAnomaly]:
        return await self.list_open_ai_anomalies(tenant_id)

    async def comparative_pnl(
        self,
        tenant_id: uuid.UUID,
        current_from: date,
        current_to: date,
        prior_from: date,
        prior_to: date,
    ) -> ComparativePnl:
        current = await self.profit_and_loss(tenant_id, current_from, current_to)
        prior = await self.profit_and_loss(tenant_id, prior_from, prior_to)
        by_code = {line.code: line for line in prior.revenue + prior.expenses}
        rows: list[ComparativePnlRow] = []
        for line in current.revenue + current.expenses:
            prior_line = by_code.get(line.code)
            prior_amount = prior_line.amount if prior_line else Decimal("0")
            variance = line.amount - prior_amount
            variance_pct = (
                (variance / prior_amount).quantize(Decimal("0.0001"))
                if prior_amount
                else Decimal("0")
            )
            rows.append(
                ComparativePnlRow(
                    account_code=line.code,
                    account_name=line.name,
                    current_amount=line.amount,
                    prior_amount=prior_amount,
                    variance=variance,
                    variance_pct=variance_pct,
                )
            )
        return ComparativePnl(
            current_from=current_from,
            current_to=current_to,
            prior_from=prior_from,
            prior_to=prior_to,
            rows=tuple(rows),
        )

    async def reverse_journal_entry(
        self,
        entry_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        reversed_by_user_id: uuid.UUID,
        reversed_at: datetime,
    ) -> JournalEntry | None:
        stmt = select(ErpJournalEntryModel).where(
            ErpJournalEntryModel.tenant_id == tenant_id,
            ErpJournalEntryModel.id == entry_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None or model.status != EntryStatus.POSTED:
            return None
        if model.reversal_entry_id is not None:
            return None

        source_lines = await self._journal_lines(entry_id, tenant_id)
        reversal = ErpJournalEntryModel(
            tenant_id=tenant_id,
            entry_date=model.entry_date,
            memo=f"Reversal of {model.memo or model.id}",
            status=EntryStatus.POSTED,
            source="manual",
            source_ref=None,
            posted_at=reversed_at,
            posted_by_user_id=reversed_by_user_id,
            reversal_entry_id=None,
        )
        self.session.add(reversal)
        await self.session.flush()
        reversal_line_models = [
            ErpJournalLineModel(
                tenant_id=tenant_id,
                entry_id=reversal.id,
                account_id=line.account_id,
                debit=line.credit,
                credit=line.debit,
                currency=line.currency,
            )
            for line in source_lines
        ]
        self.session.add_all(reversal_line_models)
        model.reversal_entry_id = reversal.id
        await self.session.flush()
        await self.session.refresh(model)
        lines = await self._journal_lines(entry_id, tenant_id)
        return _journal_entry_from_orm(model, lines)

    # --- Tenant settings (KV store) ---

    async def get_tenant_setting(self, tenant_id: uuid.UUID, key: str) -> TenantSetting | None:
        stmt = select(ErpTenantSettingModel).where(
            ErpTenantSettingModel.tenant_id == tenant_id,
            ErpTenantSettingModel.key == key,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _tenant_setting_from_orm(model) if model else None

    async def upsert_tenant_setting(
        self, tenant_id: uuid.UUID, key: str, value: str
    ) -> TenantSetting:
        stmt = select(ErpTenantSettingModel).where(
            ErpTenantSettingModel.tenant_id == tenant_id,
            ErpTenantSettingModel.key == key,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            model = ErpTenantSettingModel(tenant_id=tenant_id, key=key, value=value)
            self.session.add(model)
        else:
            model.value = value
        await self.session.flush()
        await self.session.refresh(model)
        return _tenant_setting_from_orm(model)

    # --- AI suggestion / anomaly persistence ---

    async def upsert_ai_suggestion(
        self, tenant_id: uuid.UUID, suggestion: AiFinanceSuggestion
    ) -> AiFinanceSuggestion:
        stmt = select(AiFinanceSuggestionModel).where(
            AiFinanceSuggestionModel.tenant_id == tenant_id,
            AiFinanceSuggestionModel.description == suggestion.description,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            model = AiFinanceSuggestionModel(
                tenant_id=tenant_id,
                description=suggestion.description,
                suggested_code=suggestion.suggested_code,
                suggested_name=suggestion.suggested_name,
                confidence=suggestion.confidence,
            )
            self.session.add(model)
        else:
            model.suggested_code = suggestion.suggested_code
            model.suggested_name = suggestion.suggested_name
            model.confidence = suggestion.confidence
        await self.session.flush()
        await self.session.refresh(model)
        return _ai_suggestion_from_orm(model)

    async def upsert_ai_anomaly(
        self, tenant_id: uuid.UUID, anomaly: AiFinanceAnomaly
    ) -> AiFinanceAnomaly:
        stmt = select(AiFinanceAnomalyModel).where(
            AiFinanceAnomalyModel.tenant_id == tenant_id,
            AiFinanceAnomalyModel.entity_type == anomaly.entity_type,
            AiFinanceAnomalyModel.entity_id == anomaly.entity_id,
            AiFinanceAnomalyModel.anomaly_type == anomaly.anomaly_type,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            model = AiFinanceAnomalyModel(
                tenant_id=tenant_id,
                entity_type=anomaly.entity_type,
                entity_id=anomaly.entity_id,
                anomaly_type=anomaly.anomaly_type,
                severity=anomaly.severity,
                description=anomaly.description,
            )
            self.session.add(model)
        else:
            model.severity = anomaly.severity
            model.description = anomaly.description
        await self.session.flush()
        await self.session.refresh(model)
        return _ai_anomaly_from_orm(model)

    async def list_open_ai_anomalies(self, tenant_id: uuid.UUID) -> Sequence[AiFinanceAnomaly]:
        stmt = (
            select(AiFinanceAnomalyModel)
            .where(
                AiFinanceAnomalyModel.tenant_id == tenant_id,
                AiFinanceAnomalyModel.status == "open",
            )
            .order_by(AiFinanceAnomalyModel.detected_at.desc())
        )
        models = (await self.session.execute(stmt)).scalars().all()
        return [_ai_anomaly_from_orm(m) for m in models]

    async def get_ai_anomaly(
        self, tenant_id: uuid.UUID, anomaly_id: uuid.UUID
    ) -> AiFinanceAnomaly | None:
        model = (
            await self.session.execute(
                select(AiFinanceAnomalyModel).where(
                    AiFinanceAnomalyModel.tenant_id == tenant_id,
                    AiFinanceAnomalyModel.id == anomaly_id,
                )
            )
        ).scalar_one_or_none()
        return _ai_anomaly_from_orm(model) if model else None

    async def get_invoice_by_id(
        self, tenant_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> Invoice | None:
        model = (
            await self.session.execute(
                select(ErpInvoiceModel).where(
                    ErpInvoiceModel.tenant_id == tenant_id,
                    ErpInvoiceModel.id == invoice_id,
                )
            )
        ).scalar_one_or_none()
        if model is None:
            return None
        line_models = (
            await self.session.execute(
                select(ErpInvoiceLineModel).where(
                    ErpInvoiceLineModel.invoice_id == model.id
                )
            )
        ).scalars().all()
        lines = [_invoice_line_from_orm(lm) for lm in line_models]
        return _invoice_from_orm(model, lines)

    async def list_invoices_overdue(self, tenant_id: uuid.UUID) -> Sequence[Invoice]:
        from datetime import date as _date

        stmt = (
            select(ErpInvoiceModel)
            .where(
                ErpInvoiceModel.tenant_id == tenant_id,
                ErpInvoiceModel.status.in_([InvoiceStatus.ISSUED, InvoiceStatus.APPROVED]),
                ErpInvoiceModel.due_date < _date.today(),
            )
            .order_by(ErpInvoiceModel.due_date.asc())
        )
        models = (await self.session.execute(stmt)).scalars().all()
        invoices = []
        for model in models:
            line_models = (
                await self.session.execute(
                    select(ErpInvoiceLineModel).where(
                        ErpInvoiceLineModel.invoice_id == model.id
                    )
                )
            ).scalars().all()
            invoices.append(_invoice_from_orm(model, [_invoice_line_from_orm(lm) for lm in line_models]))
        return invoices
