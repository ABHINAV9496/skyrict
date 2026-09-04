"""erp_leave_types - tenant-scoped leave catalogue (per-tenant accrual policy).

Tenant-scoped, NOT global: accrual policy is a per-tenant decision. Seeded per
tenant with defaults annual (is_accrual, 20 days) / sick / unpaid; tenants may
add more. Accrual types get balance rows (capped by CHECK balance >= 0);
non-accrual types are tracked via movements only and never get balance rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class LeaveTypeModel(Base):
    """A leave type (code) available within a tenant."""

    __tablename__ = "erp_leave_types"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_erp_leave_types_tenant_code"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_accrual: Mapped[bool] = mapped_column(Boolean, nullable=False)
    accrual_days_per_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
