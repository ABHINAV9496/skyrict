"""Tenant-scoped stock-health report snapshot ORM model (INV-ANL-001).

A computed report payload persisted per ``(tenant_id, definition_slug,
period)`` so history is queryable and a manual refresh is idempotent per
definition+period (mirrors the M-RPT snapshot convention documented in
docs/architecture/erp-phase1.md). The ``payload`` is the shaped HTTP response
object so a stored snapshot reproduces a past view exactly.

Composite-PK + RLS convention identical to every sibling ``erp_*`` table.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpReportSnapshotModel(Base):
    __tablename__ = "erp_report_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "definition_slug",
            "period",
            name="uq_erp_report_snapshots_def_period",
        ),
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
    definition_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
