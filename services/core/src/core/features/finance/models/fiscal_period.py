"""erp_fiscal_periods — accounting periods that can be closed to freeze history.

An entry belongs to a period by date (``entry_date`` falls within start/end),
not by FK; the closed-period gate in the service compares dates. The database
rejects an inverted range and duplicate period names per tenant.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpFiscalPeriodModel(Base):
    __tablename__ = "erp_fiscal_periods"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_erp_fiscal_periods_tenant_name"),
        CheckConstraint("end_date >= start_date", name="ck_erp_fiscal_periods_date_range"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
