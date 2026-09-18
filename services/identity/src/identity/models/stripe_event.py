"""Processed Stripe webhook event marker - persisted idempotency store.

One row per Stripe event that has been applied. ``event_id`` is UNIQUE so a
duplicate delivery (Stripe retries any non-2xx or timed-out webhook) is
detected atomically by ``INSERT ... ON CONFLICT DO NOTHING`` before any state
mutation runs. Rows live in the same transaction as the billing state change
they guard, so a rolled-back handler also rolls back its marker (at-least-once
delivery, no partial state).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from identity.models.base import Base, UUIDPrimaryKeyMixin


class ProcessedStripeEventModel(UUIDPrimaryKeyMixin, Base):
    """Idempotency marker for a processed Stripe webhook event."""

    __tablename__ = "processed_stripe_events"

    event_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
