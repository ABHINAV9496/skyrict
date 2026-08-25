"""Read-only projection of the shared ``tenants`` table (owned by identity).

The ai agent resolves tenant slugs against this table during routing
(middleware) and then relies on Row-Level Security for isolation. This model
deliberately maps only the columns the ai agent reads — ``id``, ``slug``,
``is_active`` — and is never used for writes: identity owns the tenants table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class TenantModel(Base):
    """A tenant (organization) row from the shared identity schema."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    plan_tier: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
