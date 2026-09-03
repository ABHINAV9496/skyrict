"""Pydantic schemas for the dashboard layout suggestion endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WidgetLayoutItem(BaseModel):
    """A single widget's position and visibility in a suggested layout."""

    id: str = Field(..., max_length=64)
    order: int = Field(..., ge=0)
    cols: int = Field(default=4, ge=1, le=4)
    visible: bool = Field(default=True)


class SuggestionRequest(BaseModel):
    """Request for an AI layout suggestion."""

    current_layout: list[WidgetLayoutItem] = Field(default_factory=list)


class SuggestionResponse(BaseModel):
    """AI-suggested layout changes with reasoning."""

    suggested_layout: list[WidgetLayoutItem]
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
