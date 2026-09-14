"""ai_transcript_analyses - one row per analyzed call/meeting activity (SKY-91).

AI product data produced from a raw CRM transcript. ``summary``,
``objection_score`` (0-100), ``objections``, ``next_best_action``,
``sentiment``, and ``key_topics`` are the model's JSON interpretation,
sanitized by the engine (score clamped, sentiment coerced to the enum, lists
capped) before persistence. ``confidence`` is the model's self-assessed
certainty, clamped 0..1.

The RAW transcript is deliberately NOT stored here: it stays in core on
``erp_crm_activities.transcript_text`` (user-submitted CRM data plane).
``activity_id`` is a plain UUID with NO FK - the activity is owned by the
core service in the shared database (cross-service idiom, validated by making
the transcript write itself through core's workspace service before analysis).
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
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiTranscriptAnalysisModel(Base):
    """One transcript analysis for a CRM activity."""

    __tablename__ = "ai_transcript_analyses"
    __table_args__ = (
        CheckConstraint(
            "objection_score >= 0 AND objection_score <= 100",
            name="ck_ai_transcript_analyses_objection_score_range",
        ),
        CheckConstraint(
            "sentiment IN ('positive', 'neutral', 'negative', 'mixed')",
            name="ck_ai_transcript_analyses_sentiment",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_ai_transcript_analyses_confidence_range",
        ),
        Index("idx_transcript_analyses_tenant_activity", "tenant_id", "activity_id"),
        Index("idx_transcript_analyses_tenant_analyzed", "tenant_id", "analyzed_at"),
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
    activity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    objection_score: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    objections: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    next_best_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'neutral'")
    )
    key_topics: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    model_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'v1'")
    )
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
