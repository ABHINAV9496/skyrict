"""Finance API routes — thin wrappers over :class:`FinanceService`.

Authorization uses the ``erp.finance.*`` keys resolved at request time:
``read`` for reads, ``write`` for mutations, ``approve`` for the money-moment
actions (post entry / approve invoice / close period). Responses use the
standard ``skyrict_common`` envelope; list endpoints are offset/limit paged
(``total`` reflects the returned page in v1).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends

from core.api.deps import get_finance_service, require_permission
from core.features.finance.schemas import (
    AccountCreateRequest,
    AccountResponse,
    BalanceSheetResponse,
    FiscalPeriodCreateRequest,
    FiscalPeriodResponse,
    InvoiceCreateRequest,
    InvoiceResponse,
    JournalEntryCreateRequest,
    JournalEntryResponse,
    PaymentApplyRequest,
    PaymentResponse,
    ProfitAndLossResponse,
    TrialBalanceResponse,
)
from core.features.finance.service import (
    FinanceService,
    InvoiceLineInput,
    JournalLineInput,
)
from skyrict_common.schemas import ListResponse, PaginationMeta, ResponseEnvelope

router = APIRouter(prefix="/finance", tags=["finance"])

# Module-level permission guards (B008: no calls in argument defaults).
require_finance_read = require_permission("erp.finance.read")
require_finance_write = require_permission("erp.finance.write")
require_finance_approve = require_permission("erp.finance.approve")


def _tenant_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["tenant_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


def _user_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["user_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


# ---------------------------------------------------------------------------
# Chart of accounts
# ---------------------------------------------------------------------------


@router.post("/accounts", response_model=ResponseEnvelope[AccountResponse], status_code=201)
async def create_account(
    body: AccountCreateRequest,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[AccountResponse]:
    account = await svc.create_account(
        tenant_id=_tenant_id(current_user),
        code=body.code,
        name=body.name,
        account_type=body.account_type,
    )
    return ResponseEnvelope(data=AccountResponse.model_validate(account))


@router.get("/accounts", response_model=ResponseEnvelope[list[AccountResponse]])
async def list_accounts(
    include_inactive: bool = False,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[list[AccountResponse]]:
    accounts = await svc.list_accounts(_tenant_id(current_user), include_inactive=include_inactive)
    return ResponseEnvelope(data=[AccountResponse.model_validate(a) for a in accounts])


@router.delete("/accounts/{account_id}", response_model=ResponseEnvelope[AccountResponse])
async def deactivate_account(
    account_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[AccountResponse]:
    account = await svc.deactivate_account(_tenant_id(current_user), account_id)
    return ResponseEnvelope(data=AccountResponse.model_validate(account))


# ---------------------------------------------------------------------------
# Journal entries
# ---------------------------------------------------------------------------


@router.post(
    "/journal-entries", response_model=ResponseEnvelope[JournalEntryResponse], status_code=201
)
async def create_journal_entry(
    body: JournalEntryCreateRequest,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[JournalEntryResponse]:
    entry = await svc.create_manual_entry(
        tenant_id=_tenant_id(current_user),
        entry_date=body.entry_date,
        memo=body.memo,
        lines=[
            JournalLineInput(account_code=line.account_code, debit=line.debit, credit=line.credit)
            for line in body.lines
        ],
    )
    return ResponseEnvelope(data=JournalEntryResponse.model_validate(entry))


@router.get("/journal-entries", response_model=ListResponse[JournalEntryResponse])
async def list_journal_entries(
    status: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    offset: int = 0,
    limit: int = 50,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceService = Depends(get_finance_service),
) -> ListResponse[JournalEntryResponse]:
    entries = await svc.list_journal_entries(
        _tenant_id(current_user),
        status=_parse_entry_status(status),
        from_date=from_date,
        to_date=to_date,
        offset=offset,
        limit=limit,
    )
    return ListResponse(
        data=[JournalEntryResponse.model_validate(e) for e in entries],
        meta=PaginationMeta.create(
            total=len(entries), page=(offset // limit) + 1 if limit else 1, page_size=limit
        ),
    )


@router.get("/journal-entries/{entry_id}", response_model=ResponseEnvelope[JournalEntryResponse])
async def get_journal_entry(
    entry_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[JournalEntryResponse]:
    entry = await svc.get_journal_entry(_tenant_id(current_user), entry_id)
    return ResponseEnvelope(data=JournalEntryResponse.model_validate(entry))


@router.post(
    "/journal-entries/{entry_id}/post",
    response_model=ResponseEnvelope[JournalEntryResponse],
)
async def post_journal_entry(
    entry_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_approve),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[JournalEntryResponse]:
    entry = await svc.post_journal_entry(
        tenant_id=_tenant_id(current_user),
        user_id=_user_id(current_user),
        entry_id=entry_id,
    )
    return ResponseEnvelope(data=JournalEntryResponse.model_validate(entry))


@router.post(
    "/journal-entries/{entry_id}/void",
    response_model=ResponseEnvelope[JournalEntryResponse],
)
async def void_journal_entry(
    entry_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[JournalEntryResponse]:
    entry = await svc.void_journal_entry(
        tenant_id=_tenant_id(current_user),
        user_id=_user_id(current_user),
        entry_id=entry_id,
    )
    return ResponseEnvelope(data=JournalEntryResponse.model_validate(entry))


# ---------------------------------------------------------------------------
# Fiscal periods
# ---------------------------------------------------------------------------


@router.post(
    "/fiscal-periods", response_model=ResponseEnvelope[FiscalPeriodResponse], status_code=201
)
async def create_fiscal_period(
    body: FiscalPeriodCreateRequest,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[FiscalPeriodResponse]:
    period = await svc.create_fiscal_period(
        tenant_id=_tenant_id(current_user),
        name=body.name,
        start_date=body.start_date,
        end_date=body.end_date,
    )
    return ResponseEnvelope(data=FiscalPeriodResponse.model_validate(period))


@router.get("/fiscal-periods", response_model=ResponseEnvelope[list[FiscalPeriodResponse]])
async def list_fiscal_periods(
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[list[FiscalPeriodResponse]]:
    periods = await svc.list_fiscal_periods(_tenant_id(current_user))
    return ResponseEnvelope(data=[FiscalPeriodResponse.model_validate(p) for p in periods])


@router.post(
    "/fiscal-periods/{period_id}/close",
    response_model=ResponseEnvelope[FiscalPeriodResponse],
)
async def close_fiscal_period(
    period_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_approve),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[FiscalPeriodResponse]:
    period = await svc.close_fiscal_period(_tenant_id(current_user), period_id)
    return ResponseEnvelope(data=FiscalPeriodResponse.model_validate(period))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------


@router.post("/invoices", response_model=ResponseEnvelope[InvoiceResponse], status_code=201)
async def create_invoice(
    body: InvoiceCreateRequest,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[InvoiceResponse]:
    invoice = await svc.create_manual_invoice(
        tenant_id=_tenant_id(current_user),
        user_id=_user_id(current_user),
        customer_id=body.customer_id,
        invoice_date=body.invoice_date,
        due_date=body.due_date,
        lines=[
            InvoiceLineInput(
                description=line.description,
                account_code=line.account_code,
                quantity=line.quantity,
                unit_price=line.unit_price,
            )
            for line in body.lines
        ],
    )
    return ResponseEnvelope(data=InvoiceResponse.model_validate(invoice))


@router.get("/invoices", response_model=ListResponse[InvoiceResponse])
async def list_invoices(
    status: str | None = None,
    offset: int = 0,
    limit: int = 50,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceService = Depends(get_finance_service),
) -> ListResponse[InvoiceResponse]:
    invoices = await svc.list_invoices(
        _tenant_id(current_user),
        status=_parse_invoice_status(status),
        offset=offset,
        limit=limit,
    )
    return ListResponse(
        data=[InvoiceResponse.model_validate(i) for i in invoices],
        meta=PaginationMeta.create(
            total=len(invoices), page=(offset // limit) + 1 if limit else 1, page_size=limit
        ),
    )


@router.get("/invoices/{invoice_id}", response_model=ResponseEnvelope[InvoiceResponse])
async def get_invoice(
    invoice_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[InvoiceResponse]:
    invoice = await svc.get_invoice(_tenant_id(current_user), invoice_id)
    return ResponseEnvelope(data=InvoiceResponse.model_validate(invoice))


@router.post("/invoices/{invoice_id}/issue", response_model=ResponseEnvelope[InvoiceResponse])
async def issue_invoice(
    invoice_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[InvoiceResponse]:
    invoice = await svc.issue_invoice(
        tenant_id=_tenant_id(current_user),
        user_id=_user_id(current_user),
        invoice_id=invoice_id,
    )
    return ResponseEnvelope(data=InvoiceResponse.model_validate(invoice))


@router.post(
    "/invoices/{invoice_id}/approve",
    response_model=ResponseEnvelope[InvoiceResponse],
)
async def approve_invoice(
    invoice_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_approve),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[InvoiceResponse]:
    invoice = await svc.approve_invoice(
        tenant_id=_tenant_id(current_user),
        user_id=_user_id(current_user),
        invoice_id=invoice_id,
    )
    return ResponseEnvelope(data=InvoiceResponse.model_validate(invoice))


@router.post("/invoices/{invoice_id}/void", response_model=ResponseEnvelope[InvoiceResponse])
async def void_invoice(
    invoice_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[InvoiceResponse]:
    invoice = await svc.void_invoice(
        tenant_id=_tenant_id(current_user),
        user_id=_user_id(current_user),
        invoice_id=invoice_id,
    )
    return ResponseEnvelope(data=InvoiceResponse.model_validate(invoice))


@router.post(
    "/invoices/{invoice_id}/payments",
    response_model=ResponseEnvelope[PaymentResponse],
    status_code=201,
)
async def apply_payment(
    invoice_id: uuid.UUID,
    body: PaymentApplyRequest,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[PaymentResponse]:
    payment = await svc.apply_payment(
        tenant_id=_tenant_id(current_user),
        user_id=_user_id(current_user),
        invoice_id=invoice_id,
        amount=body.amount,
        method=body.method,
        paid_at=body.paid_at,
    )
    return ResponseEnvelope(data=PaymentResponse.model_validate(payment))


@router.get("/payments/{payment_id}", response_model=ResponseEnvelope[PaymentResponse])
async def get_payment(
    payment_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[PaymentResponse]:
    payment = await svc.get_payment(_tenant_id(current_user), payment_id)
    return ResponseEnvelope(data=PaymentResponse.model_validate(payment))


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@router.get("/reports/trial-balance", response_model=ResponseEnvelope[TrialBalanceResponse])
async def get_trial_balance(
    as_of: date,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[TrialBalanceResponse]:
    report = await svc.trial_balance(_tenant_id(current_user), as_of)
    return ResponseEnvelope(data=TrialBalanceResponse.model_validate(report))


@router.get("/reports/profit-and-loss", response_model=ResponseEnvelope[ProfitAndLossResponse])
async def get_profit_and_loss(
    from_date: date,
    to_date: date,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[ProfitAndLossResponse]:
    report = await svc.profit_and_loss(_tenant_id(current_user), from_date, to_date)
    return ResponseEnvelope(data=ProfitAndLossResponse.model_validate(report))


@router.get("/reports/balance-sheet", response_model=ResponseEnvelope[BalanceSheetResponse])
async def get_balance_sheet(
    as_of: date,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceService = Depends(get_finance_service),
) -> ResponseEnvelope[BalanceSheetResponse]:
    report = await svc.balance_sheet(_tenant_id(current_user), as_of)
    return ResponseEnvelope(data=BalanceSheetResponse.model_validate(report))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_entry_status(value: str | None) -> Any:
    if value is None:
        return None
    from core.domain.value_objects import EntryStatus

    return EntryStatus(value)


def _parse_invoice_status(value: str | None) -> Any:
    if value is None:
        return None
    from core.domain.value_objects import InvoiceStatus

    return InvoiceStatus(value)
