"""erp_notification_prefs - per-user, per-category channel preferences.

Defaults are the category registry's defaults (``in_app`` on, email/webhook
off); a row is created lazily the first time a category is seen for a user.
Mandatory categories (compliance) ignore ``in_app_on = false`` server-side:
the producer and the preferences API both force it back to true
(``erp_notification_prefs`` is never a place to hide a compliance notice).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpNotificationPrefModel(Base):
    """One user's channel preferences for one notification category."""

    __tablename__ = "erp_notification_prefs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "category",
            name="uq_erp_notification_prefs_tenant_user_category",
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
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    in_app_on: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=func.true())
    email_on: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=func.false())
    webhook_on: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=func.false())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
