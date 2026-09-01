"""Pydantic request/response schemas for the payroll API (HR-BE-002 §2, §7).

Every response value serializes the pure-domain entities from
``core.domain.entities``; ``Money`` fields are flattened to
``{amount, currency}`` via ``MoneyOut`` because Pydantic cannot coerce the
``Money`` value object directly.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from core.domain.entities import (
    Compensation,
    PayrollEntry,
    PayrollRun,
    PayrollSettings,
    Payslip,
    PayslipReview,
)
from core.domain.value_objects import Money


class MoneyOut(BaseModel):
    """A monetary amount flattened to JSON (amount + ISO 4217 currency)."""

    amount: Decimal
    currency: str

    @field_validator("amount", mode="after")
    @classmethod
    def _quantize_amount(cls, value: Decimal) -> Decimal:
        # The DB stores Money as NUMERIC(18,4); the API contract renders money
        # with exactly two decimals ("5000.00"), matching the display convention.
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @classmethod
    def from_money(cls, money: Money | None) -> MoneyOut | None:
        if money is None:
            return None
        return cls(amount=money.amount, currency=money.currency)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class PayrollSettingsIn(BaseModel):
    """Partial settings update — omitted fields keep their current values."""

    default_currency: str | None = Field(default=None, min_length=3, max_length=3)
    pf_rate: Decimal | None = Field(default=None, ge=0, le=1)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=1)
    rounding: Literal["nearest", "up", "down"] | None = None
    ai_automation_enabled: bool | None = None
    je_bridge_enabled: bool | None = None


class PayrollSettingsOut(BaseModel):
    tenant_id: uuid.UUID
    default_currency: str
    pf_rate: Decimal
    tax_rate: Decimal
    rounding: str
    ai_automation_enabled: bool
    je_bridge_enabled: bool

    @field_validator("pf_rate", "tax_rate", mode="after")
    @classmethod
    def _normalize_rate(cls, value: Decimal) -> Decimal:
        # The DB stores rates as NUMERIC(18,4); the API renders them with two
        # decimals ("0.05", "0.10") except a zero rate, which renders as "0".
        q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return Decimal("0") if q.is_zero() else q

    @classmethod
    def from_entity(cls, settings: PayrollSettings) -> PayrollSettingsOut:
        return cls(
            tenant_id=settings.tenant_id,
            default_currency=settings.default_currency,
            pf_rate=settings.pf_rate,
            tax_rate=settings.tax_rate,
            rounding=settings.rounding.value,
            ai_automation_enabled=settings.ai_automation_enabled,
            je_bridge_enabled=settings.je_bridge_enabled,
        )


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


class PayrollRunCreate(BaseModel):
    period_start: date
    period_end: date


class PayrollRunOut(BaseModel):
    id: uuid.UUID
    run_code: str
    period_start: date
    period_end: date
    status: str
    total_gross: MoneyOut | None = None
    total_net: MoneyOut | None = None
    computed_by: uuid.UUID | None = None
    approved_by: uuid.UUID | None = None
    paid_by: uuid.UUID | None = None
    computed_at: datetime | None = None
    approved_at: datetime | None = None
    paid_at: datetime | None = None
    void_reason: str | None = None
    skipped_employees: list[SkippedEmployeeOut] | None = None
    je_bridge_status: str = "none"
    created_at: datetime | None = None

    @classmethod
    def from_entity(cls, run: PayrollRun) -> PayrollRunOut:
        assert run.id is not None
        return cls(
            id=run.id,
            run_code=run.run_code,
            period_start=run.period_start,
            period_end=run.period_end,
            status=run.status.value,
            total_gross=MoneyOut.from_money(run.total_gross),
            total_net=MoneyOut.from_money(run.total_net),
            computed_by=run.computed_by,
            approved_by=run.approved_by,
            paid_by=run.paid_by,
            computed_at=run.computed_at,
            approved_at=run.approved_at,
            paid_at=run.paid_at,
            void_reason=run.void_reason,
            skipped_employees=(
                [
                    SkippedEmployeeOut(
                        employee_id=uuid.UUID(item["employee_id"]), reason=item["reason"]
                    )
                    for item in run.skipped_employees
                ]
                if run.skipped_employees
                else None
            ),
            je_bridge_status=run.je_bridge_status.value,
            created_at=run.created_at,
        )


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------


class PayrollEntryOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    base_salary: MoneyOut
    pay_days: int
    gross: MoneyOut
    deductions: MoneyOut
    net: MoneyOut
    adjustments: dict[str, object] | None = None
    created_at: datetime | None = None

    @classmethod
    def from_entity(cls, entry: PayrollEntry) -> PayrollEntryOut:
        assert entry.id is not None
        return cls(
            id=entry.id,
            employee_id=entry.employee_id,
            base_salary=MoneyOut(
                amount=entry.base_salary.amount, currency=entry.base_salary.currency
            ),
            pay_days=entry.pay_days,
            gross=MoneyOut(amount=entry.gross.amount, currency=entry.gross.currency),
            deductions=MoneyOut(amount=entry.deductions.amount, currency=entry.deductions.currency),
            net=MoneyOut(amount=entry.net.amount, currency=entry.net.currency),
            adjustments=entry.adjustments,
            created_at=entry.created_at,
        )


class EntryAdjustmentIn(BaseModel):
    """Free-form adjustment map applied to a draft/computed entry."""

    adjustments: dict[str, object]


class SkippedEmployeeOut(BaseModel):
    employee_id: uuid.UUID
    reason: str


class PayslipOut(BaseModel):
    """One employee's payslip in a run (HR-AUT-001, Commit 4)."""

    employee_id: uuid.UUID
    employee_number: str
    employee_name: str
    gross: MoneyOut
    deductions: MoneyOut
    net: MoneyOut

    @classmethod
    def from_entity(cls, payslip: Payslip) -> PayslipOut:
        return cls(
            employee_id=payslip.employee_id,
            employee_number=payslip.employee_number,
            employee_name=payslip.employee_name,
            gross=MoneyOut(amount=payslip.gross.amount, currency=payslip.gross.currency),
            deductions=MoneyOut(
                amount=payslip.deductions.amount, currency=payslip.deductions.currency
            ),
            net=MoneyOut(amount=payslip.net.amount, currency=payslip.net.currency),
        )


class RunComputeOut(BaseModel):
    """Result of POST /runs/{id}/compute — run snapshot + entries + skips."""

    run: PayrollRunOut
    entries: list[PayrollEntryOut] = Field(default_factory=list)
    skipped: list[SkippedEmployeeOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Payslip reviews (HR-AUT-001, Commit 2)
# ---------------------------------------------------------------------------


class PayslipReviewOut(BaseModel):
    """One versioned payslip review row with its approval lifecycle."""

    id: uuid.UUID
    run_id: uuid.UUID
    employee_id: uuid.UUID
    employee_number: str
    employee_name: str
    gross: MoneyOut
    deductions: MoneyOut
    net: MoneyOut
    status: str
    version: int
    rejected_reason: str | None = None
    reviewed_by: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    rejected_by: uuid.UUID | None = None
    rejected_at: datetime | None = None
    created_at: datetime | None = None

    @classmethod
    def from_entity(cls, review: PayslipReview) -> PayslipReviewOut:
        assert review.id is not None
        return cls(
            id=review.id,
            run_id=review.run_id,
            employee_id=review.employee_id,
            employee_number=review.employee_number,
            employee_name=review.employee_name,
            gross=MoneyOut(amount=review.gross.amount, currency=review.gross.currency),
            deductions=MoneyOut(
                amount=review.deductions.amount, currency=review.deductions.currency
            ),
            net=MoneyOut(amount=review.net.amount, currency=review.net.currency),
            status=review.status,
            version=review.version,
            rejected_reason=review.rejected_reason,
            reviewed_by=review.reviewed_by,
            reviewed_at=review.reviewed_at,
            rejected_by=review.rejected_by,
            rejected_at=review.rejected_at,
            created_at=review.created_at,
        )


class PayslipReviewActionIn(BaseModel):
    """Body for approve/reject a payslip review (reason used on reject)."""

    reason: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Compensation
# ---------------------------------------------------------------------------


class CompensationCreate(BaseModel):
    employee_id: uuid.UUID
    effective_from: date
    monthly_salary: Decimal = Field(..., gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class CompensationOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    monthly_salary: MoneyOut
    effective_from: date
    is_active: bool
    created_at: datetime | None = None

    @classmethod
    def from_entity(cls, compensation: Compensation) -> CompensationOut:
        assert compensation.id is not None
        return cls(
            id=compensation.id,
            employee_id=compensation.employee_id,
            monthly_salary=MoneyOut(
                amount=compensation.monthly_salary.amount,
                currency=compensation.monthly_salary.currency,
            ),
            effective_from=compensation.effective_from,
            is_active=compensation.is_active,
            created_at=compensation.created_at,
        )


__all__ = [
    "CompensationCreate",
    "CompensationOut",
    "EntryAdjustmentIn",
    "MoneyOut",
    "PayrollEntryOut",
    "PayrollRunCreate",
    "PayrollRunOut",
    "PayrollSettingsIn",
    "PayrollSettingsOut",
    "RunComputeOut",
    "SkippedEmployeeOut",
]
