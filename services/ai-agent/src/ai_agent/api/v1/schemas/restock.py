"""Request/response schemas for restock suggestion endpoints (spec §3.5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class SuggestionItem(BaseModel):
    """One GET /ai/suggestions entry."""

    id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    current_stock: Decimal
    reorder_point: Decimal
    suggested_qty: Decimal
    estimated_cost: Decimal | None = None
    reason: str
    confidence: Decimal | None = None
    status: str
    review_note: str | None = None
    created_at: datetime


class SuggestionListResponse(BaseModel):
    """GET /ai/suggestions response with pending/total meta (spec §3.5)."""

    data: list[SuggestionItem]
    meta: dict[str, int]


class ReviewDecisionRequest(BaseModel):
    """POST /ai/suggestions/{id}/approve|reject body."""

    note: str | None = Field(default=None, max_length=500)


class ScanResponse(BaseModel):
    """POST /ai/suggestions/scan response."""

    created: int
    skipped_pending: int
    considered: int
