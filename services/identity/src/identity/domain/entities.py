"""Domain entities — pure Python dataclasses, no framework dependencies.

These represent the core business objects of the identity domain.
Services operate on these, not on ORM models directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID


class ScopeType(Enum):
    """Scope an RBAC grant applies to."""

    TENANT = "tenant"
    ORG = "org"
    WORKSPACE = "workspace"
    DEPARTMENT = "department"
    TEAM = "team"


@dataclass
class User:
    """User entity."""

    tenant_id: UUID
    email: str
    password_hash: str
    full_name: str
    is_active: bool = True
    is_verified: bool = False
    mfa_enabled: bool = False
    mfa_secret: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID | None = None


@dataclass
class Tenant:
    """Tenant (organization) entity."""

    name: str
    slug: str
    is_active: bool = True
    plan_tier: str = "free"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID | None = None


@dataclass
class Session:
    """User session entity."""

    user_id: UUID
    tenant_id: UUID
    refresh_token_hash: str
    user_agent: str | None = None
    device_info: dict[str, Any] | None = None
    ip_address: str | None = None
    location: str | None = None
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_active_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    revoked_at: datetime | None = None
    id: UUID | None = None


@dataclass
class Role:
    """Role entity for RBAC."""

    id: UUID
    tenant_id: UUID
    name: str
    permissions: list[str] = field(default_factory=list)
    is_system_role: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Permission:
    """Platform-fixed permission catalog entry (no tenant)."""

    id: UUID
    key: str
    description: str = ""


@dataclass
class UserRole:
    """Grant of a role to a user within a scope."""

    id: UUID
    user_id: UUID
    role_id: UUID
    tenant_id: UUID
    scope_type: ScopeType = ScopeType.TENANT
    scope_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class AuditLog:
    """Audit log entry entity — hash-chained, append-only."""

    tenant_id: UUID
    action: str
    target: str
    actor_user_id: UUID | None = None
    details: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    hash: str = ""
    prev_hash: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID | None = None
