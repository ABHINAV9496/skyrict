"""Wave-3 automation schemas - recurring journal templates (FIN-AUT-003 B5).

Request bodies feed :class:`~core.features.finance.automation_wave3.FinanceWave3Service`;
response models validate domain entities directly (``from_attributes``), matching
the rest of the finance schemas.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class JournalTemplateLineRequest(BaseModel):
    account_code: str = Field(..., min_length=1, max_length=32)
    debit: Decimal | None = None
    credit: Decimal | None = None


class JournalTemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    cron_expression: str = Field(..., min_length=1, max_length=64)
    entry_date_offset_days: int = Field(default=0, ge=0, le=366)
    description: str | None = Field(default=None, max_length=500)
    memo: str | None = Field(default=None, max_length=500)
    lines: list[JournalTemplateLineRequest] = Field(..., min_length=2)


class JournalTemplateUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    cron_expression: str | None = Field(default=None, min_length=1, max_length=64)
    entry_date_offset_days: int | None = Field(default=None, ge=0, le=366)
    description: str | None = Field(default=None, max_length=500)
    memo: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None
    lines: list[JournalTemplateLineRequest] | None = Field(default=None, min_length=2)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class JournalTemplateLineResponse(BaseModel):
    account_code: str
    debit: Decimal | None = None
    credit: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)


class JournalTemplateResponse(BaseModel):
    id: uuid.UUID
    name: str
    cron_expression: str
    entry_date_offset_days: int
    description: str | None = None
    memo: str | None = None
    lines: list[JournalTemplateLineResponse]
    enabled: bool = True
    last_fired_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class JournalTemplateGeneratedResponse(BaseModel):
    template_id: uuid.UUID
    template_name: str
    entry_date: date
    entry_id: uuid.UUID | None = None
    memo: str | None = None
    created: bool


class JournalTemplateFailureResponse(BaseModel):
    template_id: uuid.UUID
    template_name: str
    reason: str


class JournalTemplateRunDueResponse(BaseModel):
    ran_at: datetime
    total_due: int
    generated: list[JournalTemplateGeneratedResponse]
    failed: list[JournalTemplateFailureResponse] = []
