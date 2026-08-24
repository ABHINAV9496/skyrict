"""SQLAlchemy declarative base and shared ORM mixins.

The single source of truth for the declarative ``Base`` and the mixins every
ai-agent ORM model relies on (UUID primary key, created/updated timestamps).

The ai agent owns only its AI tables; shared tables it reads (``tenants``)
are mapped read-only. Alembic migrations live under their own version table
(``alembic_version_ai``) in the shared ``skyrict_identity`` database.
"""

from __future__ import annotations

import uuid
from datetime import datetime  # resolved at runtime by SQLAlchemy

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ai-agent ORM models."""


class UUIDPrimaryKeyMixin:
    """Add a UUID primary key column (``id``)."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )


class TimestampMixin:
    """Add ``created_at`` / ``updated_at`` timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


__all__ = ["Base", "TimestampMixin", "UUIDPrimaryKeyMixin"]
