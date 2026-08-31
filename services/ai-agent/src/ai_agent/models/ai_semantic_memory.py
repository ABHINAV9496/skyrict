"""ai_semantic_memory - extracted facts from conversations.

Stores structured facts extracted by the LLM after each CRM chat turn.
Facts are categorized (preference, entity, context, instruction) and used
to provide context in future exchanges. Rows expire after 90 days.

Embeddings and vector search are deferred — this table stores text and
metadata for keyword/FTS retrieval only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiSemanticMemoryModel(Base):
    """One extracted fact for semantic recall (90-day TTL)."""

    __tablename__ = "ai_semantic_memory"
    __table_args__ = (
        Index("idx_semantic_memory_tenant_user", "tenant_id", "user_id"),
        Index(
            "idx_semantic_memory_entity",
            "tenant_id",
            "entity_type",
            "entity_id",
            postgresql_where=text(
                "entity_type IS NOT NULL AND entity_id IS NOT NULL"
            ),
        ),
        Index("idx_semantic_memory_expires", "expires_at"),
        Index("idx_semantic_memory_category", "tenant_id", "user_id", "category"),
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
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="preference | entity | context | instruction"
    )
    entity_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="lead | opportunity | customer | contact | null"
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="conversation"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now() + interval '90 days'"),
    )
