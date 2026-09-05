"""erp_report_snapshots - materialized, period-keyed report results.

A snapshot stores one report's payload for a specific (definition, period)
combination, rendered server-side by the report runner. ``UNIQUE
(tenant_id, definition_id, period)`` makes snapshot refresh idempotent:
re-running the period simply replaces the row - the acceptance criteria in
erp-phase1.md §M-RPT.

The composite FK ``(tenant_id, definition_id)`` pins a snapshot to a
definition in the same tenant; deleting a definition cascades its snapshots.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpReportSnapshotModel(Base):
    __tablename__ = "erp_report_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "definition_id",
            "period",
            name="uq_erp_report_snapshots_tenant_definition_period",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "definition_id"],
            ["erp_report_definitions.tenant_id", "erp_report_definitions.id"],
            ondelete="CASCADE",
            name="fk_erp_report_snapshots_definition",
        ),
        Index("ix_erp_report_snapshots_tenant_period", "tenant_id", "period"),
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
    definition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    payload: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, server_default=text("'[]'::jsonb")
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
