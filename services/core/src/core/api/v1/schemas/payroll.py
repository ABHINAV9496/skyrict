"""Pydantic request/response schemas for the payroll API (HR-BE-002 §2, §7).

Every response value serializes the pure-domain entities from
``core.domain.entities``; ``Money`` fields are flattened to
``{amount, currency}`` via ``MoneyOut`` because Pydantic cannot coerce the
``Money`` value object directly.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from core.domain.entities import (
    Compensation,
    PayrollEntry,
    PayrollRun,
    PayrollSettings,
)
from core.domain.value_objects import Money


class MoneyOut(BaseModel):
    """A monetary amount flattened to JSON (amount + ISO 4217 currency)."""

    amount: Decimal
    currency: str

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


class PayrollSettingsOut(BaseModel):
    tenant_id: uuid.UUID
    default_currency: str
    pf_rate: Decimal
    tax_rate: Decimal
    rounding: str

    @classmethod
    def from_entity(cls, settings: PayrollSettings) -> PayrollSettingsOut:
        return cls(
            tenant_id=settings.tenant_id,
            default_currency=settings.default_currency,
            pf_rate=settings.pf_rate,
            tax_rate=settings.tax_rate,
            rounding=settings.rounding.value,
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


class RunComputeOut(BaseModel):
    """Result of POST /runs/{id}/compute — run snapshot + entries + skips."""

    run: PayrollRunOut
    entries: list[PayrollEntryOut] = Field(default_factory=list)
    skipped: list[SkippedEmployeeOut] = Field(default_factory=list)


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
