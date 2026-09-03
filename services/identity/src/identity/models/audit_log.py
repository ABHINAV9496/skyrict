"""AuditLog ORM model - tamper-evident, hash-chained, append-only."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from identity.models.base import Base, UUIDPrimaryKeyMixin


class AuditLogModel(UUIDPrimaryKeyMixin, Base):
    """SQLAlchemy model for the audit_logs table.

    ``hash`` / ``prev_hash`` form an append-only chain computed by a
    PostgreSQL BEFORE INSERT trigger (``digest(..., 'sha256')``). UPDATE and
    DELETE are blocked by an append-only trigger. There is intentionally no
    ``updated_at`` column.
    """

    __tablename__ = "audit_logs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    actor_user = relationship("UserModel", back_populates="audit_logs")
    tenant = relationship("TenantModel", back_populates="audit_logs")
