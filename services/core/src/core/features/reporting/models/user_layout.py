"""user_dashboard_layouts - per-user dashboard layout overrides.

Each user may store one custom layout per tenant.  The ``layout`` column has
the same JSONB structure as ``erp_dashboards.layout``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class UserDashboardLayoutModel(Base):
    __tablename__ = "user_dashboard_layouts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            name="uq_user_dashboard_layouts_tenant_user",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
    )
    layout: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, server_default=text("'[]'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
