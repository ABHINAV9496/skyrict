"""erp_report_cache - tenant-scoped aggregate cache for expensive dashboard queries.

Generic JSONB cache keyed by (tenant_id, cache_key) with a 300-second default
TTL. The TTL sweep (``core sweep-report-cache``) purges expired rows; the
nightly retention pass can add hard caps.

The same SHA-256 cache key is reused by every request for the same report
parameters: e.g. ``cashflow_projection|2026-01-01``. A cache hit returns the
JSON payload; a miss computes, stores, and returns.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpReportCacheModel(Base):
    """One cached aggregate payload (300-second TTL, DB persistence)."""

    __tablename__ = "erp_report_cache"
    __table_args__ = (
        Index(
            "uq_erp_report_cache_tenant_key",
            "tenant_id",
            "cache_key",
            unique=True,
        ),
        Index("ix_erp_report_cache_expires", "expires_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    cache_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now() + interval '5 minutes'"),
    )
