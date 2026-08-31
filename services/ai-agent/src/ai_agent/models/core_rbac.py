"""Read-only projections of the shared RBAC tables (owned by the core monolith).

The ai-agent runtime gates agent tool invocation on the SAME permission keys
the core proxy edge resolves (SKY-59 scoped tools). The grants live in core's
tables (``core_roles``, ``core_user_roles``) inside the shared database, so
this service maps read-only projections of those tables — never writes, and
only the columns the runtime reads. ``core_roles.id``/`core_user_roles.id``
carry no server default in the projections because core owns the inserts; these
models exist purely to SELECT from.

The composite primary keys mirror the real tables exactly — SQLAlchemy needs
them faithful so the tenant+role join compiles to the same predicate core's
``RbacRepository`` uses.
"""

from __future__ import annotations

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class CoreRoleModel(Base):
    """One tenant-scoped role and its granted permission keys (core-owned)."""

    __tablename__ = "core_roles"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String()), nullable=False)


class CoreUserRoleModel(Base):
    """One tenant-scoped user→role grant (core-owned)."""

    __tablename__ = "core_user_roles"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
