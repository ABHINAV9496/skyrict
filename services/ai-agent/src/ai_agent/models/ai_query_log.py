"""ai_query_log - append-only log of every natural-language query (spec §2.6).

One row per NL query execution: what was asked, how the LLM parsed it, and a
short result summary for tenant-facing history views. Insert-only by design -
there is no ``updated_at`` column and the repository exposes no update/delete
path; retention is a future purge job's concern, never row mutation.

``user_id`` is a plain UUID with NO FK: it references identity users in the
same shared database but identity owns that schema (cross-service idiom,
same as core_audit_logs' ``actor_user_id``). Tenant scoping comes from the
composite PK + RLS, not from user rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiQueryLogModel(Base):
    """One executed natural-language inventory query."""

    __tablename__ = "ai_query_log"
    __table_args__ = (
        # Spec §2.6: newest-first history per tenant.
        Index("idx_ai_query_log_tenant", "tenant_id", text("created_at DESC")),
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
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Structured intent the LLM produced (entity type, filters, aggregation) -
    # kept for debugging bad parses; never executed as-is (prompt-injection
    # defense, spec §5.6).
    parsed_intent: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
