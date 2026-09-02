"""erp_dashboards — tenant-level default dashboard layouts.

Stores the default widget layout for each tenant.  The ``layout`` column holds
a JSONB array of widget descriptors:

    [
      {"id": "ai_digest", "order": 0, "cols": 4, "visible": true},
      {"id": "erp_overview", "order": 1, "cols": 4, "visible": true},
      ...
    ]

``tenant_default`` flags the single default dashboard per tenant.  Users may
override it with a personal layout in ``user_dashboard_layouts``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpDashboardModel(Base):
    __tablename__ = "erp_dashboards"
    __table_args__ = (Index("ix_erp_dashboards_tenant_default", "tenant_id", "tenant_default"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default=text("'Default'")
    )
    layout: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, server_default=text("'[]'::jsonb")
    )
    tenant_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
