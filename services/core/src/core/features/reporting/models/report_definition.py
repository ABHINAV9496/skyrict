"""erp_report_definitions - the Phase-1 report catalog per tenant.

One row per seeded report per tenant (see ``reporting.seeds``). The report's
``sql`` is the read-only, parameterized dataset query (validated by
``reporting.validation.validate_read_only_sql`` before anything is seeded),
``params`` is the JSONB allow-list of ``:name`` bind parameters the query may
accept, and ``permission_key`` gates the endpoint that serves it (all
Phase-1 definitions reference ``erp.reports.read``).

Delete is soft: definitions are versioned rather than removed, so
``erp_report_snapshots`` rows stay meaningful for trend/backfill.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpReportDefinitionModel(Base):
    __tablename__ = "erp_report_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_erp_report_definitions_tenant_slug"),
        Index("ix_erp_report_definitions_tenant_module", "tenant_id", "module"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, server_default=text("'[]'::jsonb")
    )
    permission_key: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'erp.reports.read'")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def params_tuple(self) -> tuple[str, ...]:
        """Parameters as an immutable tuple for the validator's allow-list."""
        return tuple(self.params)
