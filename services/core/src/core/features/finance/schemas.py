"""Finance API schemas — request bodies and response models.

Response models validate domain entities directly (``from_attributes``) so the
router stays a thin translation layer. Enums (status / account_type) serialize
as their string values; Decimal money fields stay exact.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from core.domain.value_objects import AccountType, EntryStatus, InvoiceStatus

# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class AccountCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=255)
    account_type: AccountType


class JournalLineRequest(BaseModel):
    account_code: str = Field(..., min_length=1, max_length=32)
    debit: Decimal | None = None
    credit: Decimal | None = None


class JournalEntryCreateRequest(BaseModel):
    entry_date: date
    memo: str | None = Field(default=None, max_length=500)
    lines: list[JournalLineRequest] = Field(..., min_length=1)


class FiscalPeriodCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    start_date: date
    end_date: date


class InvoiceLineRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=500)
    account_code: str = Field(..., min_length=1, max_length=32)
    quantity: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)


class InvoiceCreateRequest(BaseModel):
    customer_id: uuid.UUID
    invoice_date: date
    due_date: date
    lines: list[InvoiceLineRequest] = Field(..., min_length=1)


class PaymentApplyRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    method: str = Field(..., min_length=1, max_length=32)
    paid_at: datetime


# ---------------------------------------------------------------------------
# Response models (validate domain entities via from_attributes)
# ---------------------------------------------------------------------------

_RESPONSE_CONFIG: ConfigDict = {"from_attributes": True}


class AccountResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    account_type: AccountType
    is_active: bool
    created_at: datetime | None
    updated_at: datetime | None


class JournalLineResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    id: uuid.UUID
    account_id: uuid.UUID
    debit: Decimal | None
    credit: Decimal | None
    currency: str


class JournalEntryResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    id: uuid.UUID
    tenant_id: uuid.UUID
    entry_date: date
    memo: str | None
    status: EntryStatus
    source: str
    source_ref: str | None
    lines: list[JournalLineResponse]
    posted_at: datetime | None
    posted_by_user_id: uuid.UUID | None
    voided_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


class FiscalPeriodResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    start_date: date
    end_date: date
    is_closed: bool
    created_at: datetime | None
    updated_at: datetime | None


class InvoiceLineResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    id: uuid.UUID
    line_no: int
    description: str
    account_id: uuid.UUID
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


class InvoiceResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    id: uuid.UUID
    tenant_id: uuid.UUID
    invoice_number: str
    customer_id: uuid.UUID
    customer_name: str | None = None
    invoice_date: date
    due_date: date
    status: InvoiceStatus
    total: Decimal
    source: str
    source_ref: str | None
    source_order_number: str | None = None
    lines: list[InvoiceLineResponse]
    issued_at: datetime | None
    approved_at: datetime | None
    voided_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


class PaymentResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    id: uuid.UUID
    tenant_id: uuid.UUID
    payment_number: str
    invoice_id: uuid.UUID
    amount: Decimal
    method: str
    paid_at: datetime
    status: str
    source: str
    source_ref: str | None
    created_at: datetime | None
    updated_at: datetime | None


class TrialBalanceRowResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    account_id: uuid.UUID
    code: str
    name: str
    account_type: AccountType
    debit: Decimal
    credit: Decimal


class TrialBalanceResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    as_of: date
    rows: list[TrialBalanceRowResponse]
    total_debit: Decimal
    total_credit: Decimal


class PnlLineResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    account_id: uuid.UUID
    code: str
    name: str
    amount: Decimal


class ProfitAndLossResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    from_date: date
    to_date: date
    revenue: list[PnlLineResponse]
    expenses: list[PnlLineResponse]
    total_revenue: Decimal
    total_expenses: Decimal
    net_income: Decimal


class BalanceSheetLineResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    account_id: uuid.UUID
    code: str
    name: str
    balance: Decimal


class BalanceSheetResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    as_of: date
    assets: list[BalanceSheetLineResponse]
    liabilities: list[BalanceSheetLineResponse]
    equity: list[BalanceSheetLineResponse]
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal


class ArAgingBucketResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    bucket: str
    count: int
    amount: Decimal
    share: Decimal


class ArAgingResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    as_of: date
    total_ar: Decimal
    buckets: list[ArAgingBucketResponse]


# ---------------------------------------------------------------------------
# Automation response models (SKY-56/SKY-64)
# ---------------------------------------------------------------------------


class CloseChecklistItemResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    label: str
    status: str
    detail: str | None = None


class CloseChecklistResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    period_id: uuid.UUID
    period_name: str
    items: list[CloseChecklistItemResponse]
    ready: bool


class DuplicateCandidateResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    entry_id: uuid.UUID
    entry_date: date
    memo: str | None = None
    source_ref: str | None = None


class DuplicateGroupResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    key: str
    reason: str
    entries: list[DuplicateCandidateResponse]


class AccountCodeSuggestionResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    description: str
    suggested_code: str
    suggested_name: str
    confidence: Decimal
    reasoning: str = ""


class WorkingCapitalAlertResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    ratio: Decimal
    threshold: Decimal
    current_assets: Decimal
    current_liabilities: Decimal
    alert: bool


class HealthComponentResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    name: str
    score: Decimal
    weight: Decimal
    detail: str | None = None


class HealthScoreResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    overall: Decimal
    components: list[HealthComponentResponse]


class CashflowPositionResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    month: str
    opening: Decimal
    inflows: Decimal
    outflows: Decimal
    closing: Decimal


class CashflowProjectionResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    positions: list[CashflowPositionResponse]


class ComparativePnlRowResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    account_code: str
    account_name: str
    current_amount: Decimal
    prior_amount: Decimal
    variance: Decimal
    variance_pct: Decimal


class ComparativePnlResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    current_from: date
    current_to: date
    prior_from: date
    prior_to: date
    rows: list[ComparativePnlRowResponse]


class AnomalyResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    entity_type: str
    entity_id: uuid.UUID
    anomaly_type: str
    severity: str
    description: str
    status: str
    id: uuid.UUID
    detected_at: datetime


class SuggestionRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=512)


class WorkingCapitalSettingsRequest(BaseModel):
    threshold: Decimal = Field(..., gt=0)


class TenantSettingsResponse(BaseModel):
    working_capital_threshold: Decimal


class SuggestAccountCodeRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=512)
