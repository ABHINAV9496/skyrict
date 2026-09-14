"""erp_notifications - one delivery row per recipient per event.

The monetary unit of the notification center: every row is a single
recipient's inbox item. The columns packed onto it:

- ranking/digest state (``priority_score``, ``is_pinned``, ``is_digest``,
  ``digest_count``, ``digest_suppressed``),
- recipient action state (``read_at``, ``snoozed_until``),
- channel selection (``channels`` JSONB, e.g. ``{"in_app": true}``),
- content snapshot (``title``/``body``/``payload`` copied at emit time so a
  producer cannot retroactively rewrite history).

Idempotence: ``(tenant_id, recipient_user_id, dedupe_key)`` is unique, so a
producer re-emitting an event can never create a second copy for the same
user. ``digest_suppressed`` rows are hidden from the inbox but kept as audit
history of what was collapsed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpNotificationModel(Base):
    """A notification delivered to one recipient."""

    __tablename__ = "erp_notifications"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_erp_notifications_severity",
        ),
        CheckConstraint(
            "priority_score BETWEEN 0 AND 100",
            name="ck_erp_notifications_priority_score",
        ),
        CheckConstraint(
            "digest_count >= 1",
            name="ck_erp_notifications_digest_count",
        ),
        UniqueConstraint(
            "tenant_id",
            "recipient_user_id",
            "dedupe_key",
            name="uq_erp_notifications_tenant_recipient_dedupe",
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
    # Logical reference to erp_notification_events.id (no FK: events are
    # append-only and an id-only FK would be joinable across RLS scopes).
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    priority_score: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=func.text("0")
    )
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=func.false())
    is_digest: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=func.false())
    digest_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=func.text("1")
    )
    digest_suppressed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=func.false()
    )
    is_dismissible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=func.true()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    channels: Mapped[dict[str, bool]] = mapped_column(
        JSONB, nullable=False, server_default=func.text("'{\"in_app\": true}'::jsonb")
    )
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
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
