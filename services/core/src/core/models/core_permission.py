"""Platform-fixed ERP permission catalog - global (not tenant-scoped)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class CorePermissionModel(Base):
    """A platform-fixed permission key (e.g. ``erp.invoice.read``).

    Global reference data: the catalog is identical for every tenant, so it is
    never RLS-scoped. Seeded by migration 0001 from ``core.core.permissions``.
    """

    __tablename__ = "core_permissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
