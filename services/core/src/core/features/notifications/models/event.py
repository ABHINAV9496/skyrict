"""erp_notification_events - one row per inbound producer event.

Appendix/at-least-once anchor: the ``(tenant_id, dedupe_key)`` unique
constraint makes a producer's re-emission a no-op (``INSERT ... ON CONFLICT
DO NOTHING``), so retries never double-notify. ``recipient_value`` stores the
resolution spec (explicit user ids, permission keys or role names) so the
event remains auditable after recipients are resolved.

Events are append-only: no updates and no soft/hard deletes (the row is the
audit trail of "what did the platform tell its users").
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpNotificationEventModel(Base):
    """A single producer event to fan out to its recipients."""

    __tablename__ = "erp_notification_events"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_erp_notification_events_severity",
        ),
        CheckConstraint(
            "recipient_kind IN ('users', 'permission', 'role')",
            name="ck_erp_notification_events_recipient_kind",
        ),
        UniqueConstraint(
            "tenant_id",
            "dedupe_key",
            name="uq_erp_notification_events_tenant_dedupe_key",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    recipient_value: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    relevance_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    is_dismissible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=func.true()
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
