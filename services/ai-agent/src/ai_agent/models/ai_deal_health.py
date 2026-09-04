"""ai_deal_health - one row per opportunity health assessment (SKY-61 Part 11).

``health`` is the band ``green|yellow|red`` derived deterministically from the
same factor scores as leads (engagement, fit, behavior, recency, stage age).
``risk_factors``/``recommended_actions`` are the JSONB lists surfaced in the
deal-detail AI insights panel. ``engagement_velocity`` (+accelerating /
-decelerating) and ``days_in_stage`` are stored as assessed for diagnostics.

``opportunity_id`` is a plain UUID with NO FK: the opportunity is owned by the
core service in the shared database (cross-service idiom - validated by looking
the opportunity up through core's CRM API before assessing).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiDealHealthModel(Base):
    """One deterministic health assessment for a CRM opportunity."""

    __tablename__ = "ai_deal_health"
    __table_args__ = (
        CheckConstraint("health IN ('green', 'yellow', 'red')", name="ck_ai_deal_health_band"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_ai_deal_health_confidence_range"
        ),
        Index("idx_ai_deal_health_tenant", "tenant_id", "computed_at"),
        Index("idx_ai_deal_health_opportunity", "tenant_id", "opportunity_id"),
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
    opportunity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    health: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'green'"))
    confidence: Mapped[float] = mapped_column(nullable=False, server_default=text("0"))
    risk_factors: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    recommended_actions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    engagement_velocity: Mapped[float | None] = mapped_column(Float, nullable=True)
    days_in_stage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
