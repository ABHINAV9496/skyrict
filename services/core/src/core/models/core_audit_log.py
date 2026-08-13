"""core_audit_logs — tenant-scoped, tamper-evident, append-only audit trail.

Mirrors identity's ``audit_logs`` (same shared database, same contract): a
BEFORE INSERT trigger builds a SHA-256 hash chain over the previous hash plus
the immutable row fields, and a second trigger forbids direct UPDATE / DELETE.
Writes only — never update or delete through the ORM.

``actor_user_id`` is a plain UUID with NO FK: it references identity users in
the same shared database but is owned by another service's schema/RLS; validated
via ports (same idiom as the HR/Payroll actor columns in 0005).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class CoreAuditLogModel(Base):
    """One immutable core (ERP) audit event in the tenant's hash chain."""

    __tablename__ = "core_audit_logs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
