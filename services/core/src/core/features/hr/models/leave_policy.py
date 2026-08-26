"""erp_leave_policies — tenant-scoped leave policy (casual/sick days per year).

One row per tenant. Defines annual allotments for casual and sick leave,
with a chosen effective-from date. Policy changes apply at the next Jan-1
reset (lazy accrual gated by idempotency).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class LeavePolicyModel(Base):
    """One tenant's leave policy."""

    __tablename__ = "erp_leave_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_erp_leave_policies_tenant"),
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
    casual_days_per_year: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    sick_days_per_year: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    effective_from: Mapped[date] = mapped_column(nullable=False)
    last_accrual_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
