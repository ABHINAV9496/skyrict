"""Narrator API schemas (SKY-63)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class DigestResponse(BaseModel):
    status: str
    source: str
    as_of: date
    title: str | None
    summary: str | None
    points: list[str]
    caveat: str | None
    generated_at: datetime | None
    model_used: str | None
    signals: dict[str, object] | None = None
