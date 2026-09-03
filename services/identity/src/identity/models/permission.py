"""Permission ORM model - platform-fixed permission catalog."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from identity.models.base import Base, UUIDPrimaryKeyMixin


class PermissionModel(UUIDPrimaryKeyMixin, Base):
    """SQLAlchemy model for the permissions table.

    Platform-fixed catalog: entries are seeded via migration, carry no
    tenant, and act as the canonical keys roles reference (e.g.
    ``erp.invoice.approve``).
    """

    __tablename__ = "permissions"

    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
