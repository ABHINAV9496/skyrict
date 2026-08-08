"""Tenant repository port — the persistence contract the organizations service depends on.

Ports abstract persistence only (never business rules). Methods accept and
return domain entities; SQLAlchemy lives in the concrete implementation
``identity.features.organizations.repository``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from identity.domain.entities import Tenant

if TYPE_CHECKING:
    import uuid


class TenantRepositoryPort(Protocol):
    """Persistence operations for tenants/organizations."""

    async def get_by_id(self, tenant_id: str | uuid.UUID) -> Tenant | None: ...

    async def get_by_slug(self, slug: str) -> Tenant | None: ...

    async def slug_exists(self, slug: str) -> bool: ...

    async def create(self, tenant: Tenant) -> Tenant: ...

    async def mark_onboarding_complete(self, tenant_id: str | uuid.UUID) -> Tenant: ...
