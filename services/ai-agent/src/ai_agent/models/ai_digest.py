"""ai_digest_snapshots - cached cross-module narrator digests (SKY-63).

One row per narrated digest generation. ``status`` is ``generated`` when an
LLM produced a digest, ``abstained`` when the narrator deliberately declined
(e.g. no material activity, LLM disabled/unparseable) - the ``caveat`` holds a
short reason. ``signals`` stores the compact gold-signal payload the digest was
computed from, for render auditing and debugging.

Rows are insert-per-generation; "cache" semantics are derived (the repository
picks the newest row for an ``as_of`` date), so re-generation appends instead
of mutating history.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiDigestModel(Base):
    """One cross-module narrator digest snapshot for a tenant/day."""

    __tablename__ = "ai_digest_snapshots"
    __table_args__ = (
        Index(
            "idx_ai_digest_snapshots_tenant_as_of",
            "tenant_id",
            "as_of",
            text("generated_at DESC"),
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
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'generated'")
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    points: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    caveat: Mapped[str | None] = mapped_column(Text, nullable=True)
    signals: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
