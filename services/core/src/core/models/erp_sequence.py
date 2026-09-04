"""erp_sequences - tenant-scoped monotonic counters for ERP document numbering.

A row is a single per-tenant counter keyed by ``entity`` (e.g. invoice, payment,
quote). Services claim the next number with a row-locking
``UPDATE ... SET current_value = current_value + 1 ... RETURNING`` so
consecutive numbers are race-safe and never reused.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpSequenceModel(Base):
    """A per-tenant monotonic counter for one document numbering sequence."""

    __tablename__ = "erp_sequences"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entity", name="uq_erp_sequences_tenant_entity"),
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
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    current_value: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0", default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
