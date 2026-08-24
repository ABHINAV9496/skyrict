"""Request/response schemas for anomaly endpoints (spec §4.6)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AnomalyItem(BaseModel):
    """One GET /ai/anomalies entry."""

    id: uuid.UUID
    anomaly_type: str
    severity: str
    title: str
    description: str
    affected_product_id: uuid.UUID | None = None
    affected_warehouse_id: uuid.UUID | None = None
    related_movement_ids: list[uuid.UUID] = []
    status: str
    resolution_note: str | None = None
    created_at: datetime


class AnomalyListResponse(BaseModel):
    """GET /ai/anomalies response with meta counts (spec §4.6)."""

    data: list[AnomalyItem]
    meta: dict[str, int]


class AnomalyReviewRequest(BaseModel):
    """POST /ai/anomalies/{id}/resolve|dismiss|escalate body."""

    note: str | None = Field(default=None, max_length=500)


class DetectionScanResponse(BaseModel):
    """POST /ai/anomalies/scan response."""

    detected: int
    duplicates_skipped: int
