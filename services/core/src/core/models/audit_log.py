"""Read/write projection of the shared ``audit_logs`` table (owned by identity).

Core writes finance state-change audit rows into the same append-only,
hash-chained, tamper-evident trail identity maintains. This model maps the full
table so inserts flow through the DB trigger that computes ``hash`` /
``prev_hash`` and blocks UPDATE/DELETE.

``actor_user_id`` is deliberately mapped WITHOUT a ForeignKey: the ``users``
table is owned by identity and is not part of core's metadata (the DB-level FK
constraint still applies). ``tenant_id`` references core's read-only
``TenantModel`` (``tenants``). No relationships — core never navigates to
identity models.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, UUIDPrimaryKeyMixin


class AuditLogModel(UUIDPrimaryKeyMixin, Base):
    """SQLAlchemy model for the shared ``audit_logs`` table.

    ``hash`` / ``prev_hash`` form an append-only chain computed by a PostgreSQL
    BEFORE INSERT trigger (``digest(..., 'sha256')``); UPDATE and DELETE are
    blocked by an append-only trigger. There is intentionally no ``updated_at``
    column.
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
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<AuditLogModel id={self.id} action={self.action!r}>"
