"""erp_tax_summaries - draft per-category tax summaries (FIN-AI-004 A5).

A draft is built from a fiscal period's posted journal lines by the ai-agent
LLM; core persists it (DRAFT) along with the exact snapshot of accounts +
lines it was generated from, so a reviewer can trace every category figure to
its source lines. ``status`` moves draft -> approved|rejected; approval
records the acting user and time (audit-logged by the service).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpTaxSummaryModel(Base):
    __tablename__ = "erp_tax_summaries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'approved', 'rejected')",
            name="ck_erp_tax_summaries_status",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    period_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period_name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    categories: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    total_input: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, server_default=text("0")
    )
    total_output: Mapped[Decimal] = mapped_column(
        Numeric(19, 4), nullable=False, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    model_used: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("''"))
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
