"""Pydantic schemas for the dashboard layout feature."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class WidgetLayoutItem(BaseModel):
    """A single widget's position and visibility in a dashboard layout."""

    id: str = Field(..., max_length=64, description="Widget identifier from the registry")
    order: int = Field(..., ge=0, description="Sort order (0 = first)")
    cols: int = Field(default=4, ge=1, le=4, description="Grid column span (1-4)")
    visible: bool = Field(default=True, description="Whether the widget is shown")


class DashboardLayout(BaseModel):
    """A complete dashboard layout - list of widget positions."""

    widgets: list[WidgetLayoutItem] = Field(default_factory=list)


class DashboardRead(BaseModel):
    """Response for a dashboard layout read."""

    id: uuid.UUID
    title: str
    layout: list[WidgetLayoutItem]
    tenant_default: bool
    created_at: datetime
    updated_at: datetime


class UserDashboardLayoutRead(BaseModel):
    """Response for a user's personal dashboard layout."""

    layout: list[WidgetLayoutItem]
    updated_at: datetime


class DashboardUpdate(BaseModel):
    """Payload for saving a dashboard layout."""

    title: str | None = Field(default=None, max_length=128)
    layout: list[WidgetLayoutItem] = Field(default_factory=list)


class WidgetEventCreate(BaseModel):
    """Payload for recording a widget interaction event."""

    widget_id: str = Field(..., max_length=64)
    event: str = Field(..., pattern=r"^(open|hide)$")


class WidgetEventBatchCreate(BaseModel):
    """Batch payload for recording multiple widget events."""

    events: list[WidgetEventCreate] = Field(default_factory=list, max_length=100)


class AiSuggestionRequest(BaseModel):
    """Request for an AI-powered layout suggestion."""

    pass


class AiSuggestionResponse(BaseModel):
    """AI-suggested layout changes with reasoning."""

    suggested_layout: list[WidgetLayoutItem]
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
