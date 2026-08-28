"""ai_query_cache - hot (Redis) + cold (DB) query cache.

Two-layer cache: Redis serves identical queries under 50ms (hot path), while
this DB table provides persistence and analytics (hit counts, response
inspection). The hourly cleanup sweep removes expired entries.

``query_hash`` is a SHA-256 of the normalized query text (lowercased,
whitespace-collapsed, tenant-scoped). The UNIQUE constraint ensures one cache
entry per tenant+query.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiQueryCacheModel(Base):
    """One cached query-response pair (1-hour TTL, DB persistence)."""

    __tablename__ = "ai_query_cache"
    __table_args__ = (
        # One cache entry per tenant+query (migration 0003 fixed the global
        # unique constraint from 0002 to this tenant-scoped unique index).
        Index("uq_ai_query_cache_tenant_hash", "tenant_id", "query_hash", unique=True),
        Index("idx_query_cache_expires", "expires_at"),
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
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now() + interval '1 hour'"),
    )
