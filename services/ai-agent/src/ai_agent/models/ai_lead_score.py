"""ai_lead_scores - one row per deterministic lead scoring run (SKY-61 Part 11).

``score`` is the weighted sum (0-100) produced by the CRM AI scoring engine —
never an LLM number. ``factors`` is the JSONB breakdown the UI shows in the
badge tooltip (e.g. ``["engagement 80 x 0.25", ...]``). ``confidence`` reflects
how much source data the engine had to work with (0 when a lead has no
activity/contact data yet). ``UNIQUE (tenant_id, lead_id, computed_at)`` lets a
lead carry a history: a re-score INSERTs a new version rather than clobbering.

``lead_id`` is a plain UUID with NO FK: the lead row is owned by the core
service in the shared database (cross-service idiom — integrity is validated by
looking the lead up through core's CRM API before scoring).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiLeadScoreModel(Base):
    """One deterministic lead-scoring run for a CRM lead."""

    __tablename__ = "ai_lead_scores"
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="ck_ai_lead_scores_score_range"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_ai_lead_scores_confidence_range"
        ),
        # History per lead+computed_at; a re-score is a new version.
        Index("idx_ai_lead_scores_tenant_lead", "tenant_id", "lead_id"),
        Index("idx_ai_lead_scores_computed", "tenant_id", "computed_at"),
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
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    confidence: Mapped[float] = mapped_column(nullable=False, server_default=text("0"))
    factors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    model_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'v1'")
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
