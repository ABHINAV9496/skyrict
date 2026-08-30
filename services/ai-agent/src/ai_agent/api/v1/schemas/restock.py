"""Request/response schemas for restock suggestion endpoints (spec §3.5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


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


class RestockSettingsResponse(BaseModel):
    """GET /ai/suggestions/settings — the tenant's full AI settings snapshot."""

    tenant_id: uuid.UUID
    lead_time_days: Decimal
    safety_factor: Decimal
    v2_enabled: bool
    sensitivity: Decimal
    fp_threshold: Decimal
    email_alerts_enabled: bool


class RestockSettingsUpdate(BaseModel):
    """PATCH /ai/suggestions/settings body — every field optional.

    Bounds mirror the ai_restock_settings CHECK constraints so invalid values
    are rejected at the schema before they reach Postgres.
    """

    lead_time_days: Decimal | None = Field(default=None, gt=0)
    safety_factor: Decimal | None = Field(default=None, gt=0)
    v2_enabled: bool | None = None
    sensitivity: Decimal | None = Field(default=None, ge=0, le=1)
    fp_threshold: Decimal | None = Field(default=None, ge=0, le=1)
    email_alerts_enabled: bool | None = None

    @model_validator(mode="after")
    def _require_one_field(self) -> RestockSettingsUpdate:
        fields = (
            self.lead_time_days,
            self.safety_factor,
            self.v2_enabled,
            self.sensitivity,
            self.fp_threshold,
            self.email_alerts_enabled,
        )
        if all(field is None for field in fields):
            raise ValueError("at least one settings field must be provided")
        return self
