"""ai_audit_log - append-only audit trail for AI actions (spec §5.3).

One row per AI action with its full evidence: who/what triggered it, the
action vocabulary (Appendix B), sanitized input/output summaries, which LLM
answered and how long it took. Insert-only by design - no ``updated_at`` and
no update/delete path through the repository; rows are tenant-scoped via the
composite PK + RLS.

``user_id`` is a plain UUID with NO FK (identity users, cross-service idiom)
and is NULL for background jobs, mirroring the spec's "or system for
background jobs". ``input``/``output`` carry SANITIZED summaries only -
never raw prompts, provider API keys, or PII beyond what the action already
stores in its feature tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiAuditLogModel(Base):
    """One immutable AI audit event."""

    __tablename__ = "ai_audit_log"
    __table_args__ = (
        # Newest-first trail per tenant; also serves the optional action filter.
        Index("idx_ai_audit_log_tenant_created", "tenant_id", text("created_at DESC")),
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
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    input: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
