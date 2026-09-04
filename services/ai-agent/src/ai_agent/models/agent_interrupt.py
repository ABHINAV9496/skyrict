"""agent_interrupts - human-in-the-loop ledger (SKY-59, spec §3.9).

One row per interrupt raised by a graph before a write-action tool; the row
carries the full tool payload so a reviewer can approve/deny without the
graph being alive. Transitions ``pending -> approved | denied`` record the
deciding user and time. ``expires_at`` (24h by default) drives LAZY auto-deny:
any read/resume/approval of an expired pending row computes ``denied`` + an
audit row instead of a background sweeper.

MITM defense: the payload is the tool call; the graph resumes only with the
decision recorded here - an interrupt can never be answered except through
this row (same tenant, same graph run).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AgentInterruptModel(Base):
    """One pending (or decided) human-in-the-loop interrupt."""

    __tablename__ = "agent_interrupts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'denied')",
            name="ck_agent_interrupts_status",
        ),
        Index("idx_agent_interrupts_run", "tenant_id", "graph_run_id"),
        # Lazy-expiry + sweep scan: pending interrupts by soonest expiry.
        Index(
            "idx_agent_interrupts_status_expiry",
            "tenant_id",
            "status",
            "expires_at",
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
    graph_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tool: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pending'")
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now() + interval '24 hours'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
