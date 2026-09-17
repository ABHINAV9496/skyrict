"""Wave-5 automation schemas - budgets, depreciation, expense policy,
compliance calendar (FIN-AUT-004, SKY-85 B13/B16/B21/B27/B28).

Request bodies feed the four SKY-85 service modules; response models validate
domain entities directly (``from_attributes``), matching the rest of the
finance schemas.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Budgets (B21)
# ---------------------------------------------------------------------------


class BudgetCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    fiscal_year: int = Field(..., ge=2000, le=2200)
    description: str | None = Field(default=None, max_length=500)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    lines: list[BudgetLineRequest] = Field(default_factory=list)


class BudgetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class BudgetLineRequest(BaseModel):
    account_code: str = Field(..., min_length=1, max_length=32)
    amount: Decimal = Field(..., gt=Decimal("0"))


class BudgetLineResponse(BaseModel):
    id: uuid.UUID
    account_code: str
    amount: Decimal

    model_config = ConfigDict(from_attributes=True)


class BudgetResponse(BaseModel):
    id: uuid.UUID
    name: str
    fiscal_year: int
    status: str
    description: str | None = None
    currency: str = "USD"
    lines: list[BudgetLineResponse] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class BudgetVarianceLineResponse(BaseModel):
    account_code: str
    planned: Decimal
    actual: Decimal
    variance: Decimal
    variance_pct: Decimal
    flag: str


class BudgetVarianceResponse(BaseModel):
    budget_id: uuid.UUID
    name: str
    fiscal_year: int
    status: str
    currency: str = "USD"
    planned_total: Decimal = Decimal("0")
    actual_total: Decimal = Decimal("0")
    variance_total: Decimal = Decimal("0")
    flagged_count: int = 0
    lines: list[BudgetVarianceLineResponse] = []


# ---------------------------------------------------------------------------
# Fixed assets / depreciation (B13/B28)
# ---------------------------------------------------------------------------


class FixedAssetCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    cost: Decimal = Field(..., gt=Decimal("0"))
    acquisition_date: date
    useful_life_years: int = Field(..., ge=1, le=100)
    category: str | None = Field(default=None, max_length=64)
    depreciation_method: str = Field(default="straight_line", max_length=32)
    salvage_value: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))

    @model_validator(mode="after")
    def _salvage_below_cost(self) -> FixedAssetCreateRequest:
        if self.salvage_value >= self.cost:
            raise ValueError("salvage_value must be less than cost")
        return self


class FixedAssetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    category: str | None = Field(default=None, max_length=64)
    cost: Decimal | None = Field(default=None, gt=Decimal("0"))
    acquisition_date: date | None = None
    useful_life_years: int | None = Field(default=None, ge=1, le=100)
    salvage_value: Decimal | None = Field(default=None, ge=Decimal("0"))

    @model_validator(mode="after")
    def _salvage_below_cost(self) -> FixedAssetUpdateRequest:
        if (
            self.salvage_value is not None
            and self.cost is not None
            and self.salvage_value >= self.cost
        ):
            raise ValueError("salvage_value must be less than cost")
        return self


class FixedAssetResponse(BaseModel):
    id: uuid.UUID
    name: str
    category: str | None = None
    cost: Decimal
    acquisition_date: date
    useful_life_years: int
    depreciation_method: str
    salvage_value: Decimal = Decimal("0")
    accumulated_depreciation: Decimal = Decimal("0")
    net_book_value: Decimal = Decimal("0")
    status: str
    disposed_at: date | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class DepreciationRunResponse(BaseModel):
    period: str
    ran_at: datetime
    assets_considered: int = 0
    entries_created: int = 0
    entries_skipped: int = 0
    total_amount: Decimal = Decimal("0")
    entry_ids: list[uuid.UUID] = []


class DepreciationEntryResponse(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    period: str
    amount: Decimal
    status: str
    journal_entry_id: uuid.UUID | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Expense policy / claims / violations (B16)
# ---------------------------------------------------------------------------


class ExpensePolicyRequest(BaseModel):
    category: str = Field(..., min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=100)
    cap_amount: Decimal | None = Field(default=None, gt=Decimal("0"))
    requires_receipt: bool = False
    advance_limit: Decimal | None = Field(default=None, gt=Decimal("0"))


class ExpensePolicyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    cap_amount: Decimal | None = Field(default=None, gt=Decimal("0"))
    requires_receipt: bool | None = None
    advance_limit: Decimal | None = Field(default=None, gt=Decimal("0"))


class ExpensePolicyResponse(BaseModel):
    id: uuid.UUID
    category: str
    name: str | None = None
    cap_amount: Decimal | None = None
    requires_receipt: bool = False
    advance_limit: Decimal | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ExpenseClaimRequest(BaseModel):
    category: str = Field(..., min_length=1, max_length=64)
    amount: Decimal = Field(..., gt=Decimal("0"))
    description: str | None = Field(default=None, max_length=500)
    receipt_url: str | None = Field(default=None, max_length=500)
    advance_amount: Decimal | None = Field(default=None, ge=Decimal("0"))
    source_ref: str | None = Field(default=None, max_length=64)


class ExpenseClaimResponse(BaseModel):
    id: uuid.UUID
    category: str
    amount: Decimal
    description: str | None = None
    receipt_url: str | None = None
    advance_amount: Decimal | None = None
    status: str
    source_ref: str | None = None
    submitted_by: uuid.UUID | None = None
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ExpenseViolationResponse(BaseModel):
    id: uuid.UUID
    category: str
    reason_code: str
    outcome: str
    amount: Decimal
    claim_id: uuid.UUID | None = None
    submitted_by: uuid.UUID | None = None
    message: str | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ExpenseEvaluationResponse(BaseModel):
    claim: ExpenseClaimResponse
    violations: list[ExpenseViolationResponse] = []
    decision: str


# ---------------------------------------------------------------------------
# Compliance calendar (B27)
# ---------------------------------------------------------------------------


class ComplianceItemRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    due_on: date
    description: str | None = Field(default=None, max_length=500)
    obligation_type: str | None = Field(default=None, max_length=64)
    recurrence: str | None = Field(default=None, max_length=16)
    lead_days: int = Field(default=7, ge=0, le=365)


class ComplianceItemUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=150)
    due_on: date | None = None
    description: str | None = Field(default=None, max_length=500)
    obligation_type: str | None = Field(default=None, max_length=64)
    recurrence: str | None = Field(default=None, max_length=16)
    lead_days: int | None = Field(default=None, ge=0, le=365)


class ComplianceItemResponse(BaseModel):
    id: uuid.UUID
    title: str
    due_on: date
    description: str | None = None
    obligation_type: str | None = None
    recurrence: str | None = None
    lead_days: int = 7
    status: str
    assignee_id: uuid.UUID | None = None
    completed_at: datetime | None = None
    completed_by: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    overdue: bool = False

    model_config = ConfigDict(from_attributes=True)
