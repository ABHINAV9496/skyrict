"""erp_depreciation_entries - per-period depreciation accruals (SKY-85 B13/B28).

The monthly run writes ONE row per ``(asset_id, period)`` and stamps a DRAFT
journal entry via ``source='depreciation'`` + ``source_ref=f"{asset_id}:{period}"``
so the journal entries UNIQUE lock keeps runs exactly-once. ``period`` is a
``YYYY-MM`` string (indexed for scan queries).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpDepreciationEntryModel(Base):
    __tablename__ = "erp_depreciation_entries"
    __table_args__ = (
        Index("ix_erp_depreciation_entries_tenant_period", "tenant_id", "period"),
        UniqueConstraint(
            "tenant_id",
            "asset_id",
            "period",
            name="uq_erp_depreciation_entries_tenant_asset_period",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
