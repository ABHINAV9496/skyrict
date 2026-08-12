"""Domain entities — pure Python, no framework dependencies.

These are the in-memory representations the repository layer maps ORM models
to/from. They are plain (immutable) dataclasses so services can reason about
tenant-scoped RBAC grants without touching SQLAlchemy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid


@dataclass(frozen=True)
class CorePermission:
    """A platform-fixed permission key (e.g. ``erp.invoice.read``).

    Global — not tenant-scoped: the catalog is the same for every tenant.
    """

    key: str
    description: str = ""


@dataclass(frozen=True)
class CoreRole:
    """A tenant-scoped role holding a set of permission grants.

    ``permissions`` holds granted permission keys. The wildcard ``"*"`` grants
    every key in the catalog (owner role).
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    permissions: tuple[str, ...] = ()
    is_system_role: bool = False


@dataclass(frozen=True)
class CoreUserRole:
    """A tenant-scoped grant of one role to one user.

    ``user_id`` references an identity-service user (no FK at the DB level —
    identity owns users).
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role_id: uuid.UUID
    scope_id: uuid.UUID | None = field(default=None)
