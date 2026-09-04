"""ai_rag_parents - parent chunks (~2000 tokens, not embedded).

Parent chunks store the full section of text returned to the LLM for generation
context. They are NOT embedded - only their child chunks are vectorized. Each
parent links to one or more child chunks via ``ai_rag_chunks.parent_id``.

The parent-child split means retrieval is precise (small child vectors) while
generation has full context (large parent text). This is the highest-leverage
RAG accuracy pattern per 2025-2026 benchmarks (+10-15% over flat chunking).

Source references point at the originating document or transactional record;
cross-service UUID references (product, warehouse) carry no FK - integrity is
validated through service ports (repo convention).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiRagParentModel(Base):
    """One parent chunk (~2000 tokens) returned to the LLM for context."""

    __tablename__ = "ai_rag_parents"
    __table_args__ = (Index("idx_rag_parents_source", "tenant_id", "source_ref"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    module: Mapped[str] = mapped_column(String(100), nullable=False)
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
