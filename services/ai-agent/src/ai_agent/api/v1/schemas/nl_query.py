"""Request/response schemas for the NL query endpoints (spec §2.5)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class NlQueryRequest(BaseModel):
    """POST /ai/query body - one free-text inventory question."""

    query: str = Field(min_length=1, max_length=500)


class NlQueryResponse(BaseModel):
    """POST /ai/query response (spec §2.5).

    Abstentions/clarifications are 200 responses with an ``answer`` and no
    ``data`` - per the SKY-57 error contract they are NOT errors.
    """

    answer: str
    data: dict[str, object] | None = None
    model_used: str | None = None
    latency_ms: int


class QueryHistoryItem(BaseModel):
    """One GET /ai/query/history entry."""

    id: uuid.UUID
    query_text: str
    result_summary: str | None
    model_used: str | None
    latency_ms: int | None
    created_at: datetime


class QueryHistoryResponse(BaseModel):
    """GET /ai/query/history response - newest-first for the tenant."""

    data: list[QueryHistoryItem]
