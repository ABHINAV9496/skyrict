"""ai_finance_suggestions — persisted account-code suggestion rows.

Upserted on duplicate scan (deduped on tenant + description hash) and
accepted/dismissed later by humans (SKY-66)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class AiFinanceSuggestionModel(Base):
    __tablename__ = "ai_finance_suggestions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "description",
            name="uq_ai_finance_suggestions_tenant_description",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    suggested_code: Mapped[str] = mapped_column(String(32), nullable=False)
    suggested_name: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
