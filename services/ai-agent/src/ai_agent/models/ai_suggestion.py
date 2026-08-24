"""ai_suggestions - restock suggestions with the human approval workflow
(spec §3.6).

Rows are created by the daily background scan (or on-demand analysis) and then
transition ``pending -> approved | rejected | expired`` by a human. The
partial unique index enforces "at most one OPEN suggestion per tenant +
product + warehouse" so the scan can never pile up duplicate pending rows.

Money columns are NUMERIC(18,4) (repo convention - never floats).
``product_id``/``warehouse_id`` are plain UUIDs with NO FK: those tables are
owned by the core service in the same shared database; integrity is validated
through the core data-plane API before a suggestion is created (cross-service
idiom, same as core_audit_logs' ``actor_user_id``). ``reviewed_by`` likewise
references an identity user.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiSuggestionModel(Base):
    """One AI-generated restock suggestion awaiting (or past) human review."""

    __tablename__ = "ai_suggestions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name="ck_ai_suggestions_status",
        ),
        CheckConstraint("suggested_qty > 0", name="ck_ai_suggestions_suggested_qty_positive"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_ai_suggestions_confidence_range",
        ),
        # Spec §3.6: list view per tenant, newest first, status filterable.
        Index(
            "idx_ai_suggestions_tenant_status",
            "tenant_id",
            "status",
            text("created_at DESC"),
        ),
        # Spec §3.6: only one pending suggestion per product+warehouse per
        # tenant; approved/rejected/expired rows are exempt via the WHERE.
        Index(
            "idx_ai_suggestions_pending_unique",
            "tenant_id",
            "product_id",
            "warehouse_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
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
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    current_stock: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    reorder_point: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    suggested_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pending'")
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
