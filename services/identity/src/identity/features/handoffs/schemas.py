"""Handoff request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class HandoffIssueRequest(BaseModel):
    """POST /handoffs — persist an in-flight wizard/BFF payload."""

    purpose: str
    payload: dict[str, Any] = {}


class HandoffIssueResponse(BaseModel):
    """Response carrying the once-returnable raw token."""

    id: UUID
    token: str
    expires_at: datetime


class HandoffRedeemRequest(BaseModel):
    """POST /handoffs/redeem — consume a single-use token."""

    token: str
    purpose: str | None = None


class HandoffRedeemResponse(BaseModel):
    """Response resuming the in-flight wizard/BFF payload."""

    id: UUID
    purpose: str
    payload: dict[str, Any]
    expires_at: datetime
