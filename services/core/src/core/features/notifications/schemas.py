"""Notification API schemas (SKY-93).

Pydantic v2 request/response models for the notification center endpoints.
Timestamps are serialized as ISO 8601 strings; ``priority_score`` is the
0-100 computed priority that drives ordering; ``is_pinned`` marks mandatory /
critical rows that the inbox always surfaces first.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NotificationItem(BaseModel):
    """One notification row in the inbox / drawer responses."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    category: str
    module: str
    severity: str
    title: str
    body: str
    priority_score: int
    is_pinned: bool
    is_dismissible: bool
    is_digest: bool = False
    digest_count: int | None = None
    occurred_at: datetime
    read_at: datetime | None = None
    snoozed_until: datetime | None = None
    payload: dict[str, Any] | None = None


class InboxResponse(BaseModel):
    """Paginated inbox payload."""

    items: list[NotificationItem]
    total: int
    unread_count: int
    pinned_unread_count: int


class CountsResponse(BaseModel):
    """Unread + pinned-unread counters for the bell/drawer badge."""

    unread_count: int
    pinned_unread_count: int


class MarkReadResponse(BaseModel):
    """Result of marking a notification read."""

    id: uuid.UUID
    read_at: datetime


class MarkAllReadResponse(BaseModel):
    """Result of marking the whole inbox read."""

    marked: int


class SnoozeRequest(BaseModel):
    """Snooze payload; ``until`` must be in the future."""

    until: datetime

    @field_validator("until")
    @classmethod
    def until_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("until must include a timezone")
        return value


class SnoozeResponse(BaseModel):
    """Result of a snooze request (may be refused for mandatory rows)."""

    snoozed: bool
    mandated: bool = False


class PreferenceItem(BaseModel):
    """One category's effective preference row."""

    category: str
    label: str
    mandatory: bool
    in_app_on: bool
    email_on: bool
    webhook_on: bool


class PreferenceUpdate(BaseModel):
    """Upsert payload for one category's preferences."""

    in_app_on: bool = Field(default=True)
    email_on: bool = Field(default=False)
    webhook_on: bool = Field(default=False)


class PreferenceListResponse(BaseModel):
    """All category preferences for the current user."""

    items: list[PreferenceItem]
