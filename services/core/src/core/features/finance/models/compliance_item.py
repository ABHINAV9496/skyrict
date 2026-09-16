"""erp_compliance_items - recurring compliance obligations (SKY-85 B27).

``due_on`` is the next occurrence; ``recurrence`` advances it after completion
(monthly/quarterly/yearly, or NULL for one-off). ``lead_days`` is the
reminder look-ahead window. Open items with ``due_on <= today + lead_days``
drive the reminder emission into the mandatory ``compliance`` notification
category with dedupe key ``compliance:{obligation_id}:{due_on}``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpComplianceItemModel(Base):
    __tablename__ = "erp_compliance_items"
    __table_args__ = (Index("ix_erp_compliance_items_tenant_due", "tenant_id", "status", "due_on"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    obligation_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recurrence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    lead_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("7"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
