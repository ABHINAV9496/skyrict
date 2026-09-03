"""widget_events - lightweight widget interaction telemetry.

Records open/hide events per user per widget for the AI-powered layout
suggestion engine.  Events are append-only; TTL cleanup runs periodically.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class WidgetEventModel(Base):
    __tablename__ = "widget_events"
    __table_args__ = (
        CheckConstraint("event IN ('open', 'hide')", name="ck_widget_events_event"),
        Index("ix_widget_events_tenant_widget", "tenant_id", "widget_id"),
        Index("ix_widget_events_tenant_user", "tenant_id", "user_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    widget_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
