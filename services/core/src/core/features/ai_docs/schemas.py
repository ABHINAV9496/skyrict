"""AI document feature schemas (FIN-AI-004).

Pydantic request/response models for the ``/finance/ai`` routes. Decimal money
fields serialize as exact strings via the standard ``skyrict_common`` envelope
(matching every other finance endpoint).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# A5: tax summary
# ---------------------------------------------------------------------------


class TaxSummaryGenerateRequest(BaseModel):
    period_id: uuid.UUID


class TaxCategoryLine(BaseModel):
    category: str
    detail: str = ""
    input_tax: Decimal
    output_tax: Decimal
    net: Decimal


class TaxSummaryResponse(BaseModel):
    id: uuid.UUID
    period_id: uuid.UUID
    period_name: str
    start_date: date
    end_date: date
    snapshot_id: uuid.UUID | None
    categories: list[TaxCategoryLine]
    total_input: Decimal
    total_output: Decimal
    status: str
    model_used: str
    approved_by_user_id: uuid.UUID | None
    approved_at: datetime | None
    created_at: datetime


class TaxSummaryActionResponse(BaseModel):
    id: uuid.UUID
    status: str
    watermarked: bool


# ---------------------------------------------------------------------------
# A6: document packs
# ---------------------------------------------------------------------------

AI_DOC_TYPES = ("pnl", "balance_sheet", "tax_summary", "audit_narrative")


class DocPackGenerateRequest(BaseModel):
    doc_type: str = Field(pattern=r"^(pnl|balance_sheet)$")
    snapshot_id: uuid.UUID
    snapshot_data: dict[str, Any]


class AiDocResponse(BaseModel):
    id: uuid.UUID
    doc_type: str
    snapshot_id: uuid.UUID
    version: int
    status: str
    watermarked: bool
    approved_by_user_id: uuid.UUID | None
    approved_at: datetime | None
    created_at: datetime


class AiDocActionResponse(BaseModel):
    id: uuid.UUID
    status: str
    watermarked: bool
    version: int


# ---------------------------------------------------------------------------
# A10: audit narration
# ---------------------------------------------------------------------------


class AuditNarrationRequest(BaseModel):
    from_date: date
    to_date: date


class RiskArea(BaseModel):
    entry_id: str | None = None
    risk_type: str
    description: str
    severity: str


class AuditNarrationResponse(BaseModel):
    from_date: date
    to_date: date
    narration: str
    risk_areas: list[RiskArea]
    model_used: str


# ---------------------------------------------------------------------------
# A12: document Q&A
# ---------------------------------------------------------------------------


class DocQaRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class DocCitation(BaseModel):
    source_ref: str
    chunk_text: str
    score: float


class DocQaAnswer(BaseModel):
    answer: str
    citations: list[DocCitation]
    model_used: str
