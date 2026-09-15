"""erp_fixed_assets - the capital asset register (FIN-AUT-004, SKY-85 B13/B28).

Depreciation accrues straight-line from ``acquisition_date`` across
``useful_life_years`` to ``salvage_value``; the engine writes per-period rows
to ``erp_depreciation_entries`` (each with a DRAFT journal entry). Types here
are read/write only - the monthly accrual math lives in the depreciation
service so the model stays a dumb container.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpFixedAssetModel(Base):
    __tablename__ = "erp_fixed_assets"
    __table_args__ = (
        Index("ix_erp_fixed_assets_tenant_status", "tenant_id", "status"),
        UniqueConstraint("tenant_id", "name", name="uq_erp_fixed_assets_tenant_name"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    useful_life_years: Mapped[int] = mapped_column(Integer, nullable=False)
    depreciation_method: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'straight_line'")
    )
    salvage_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, server_default=text("0")
    )
    accumulated_depreciation: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'active'"))
    disposed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
