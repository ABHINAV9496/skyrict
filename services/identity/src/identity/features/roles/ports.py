"""Role repository port — the persistence contract role management depends on.

Ports abstract persistence only (never business rules). Methods accept and
return domain entities; SQLAlchemy lives in the concrete implementation
``identity.features.roles.repository``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from identity.domain.entities import Role, ScopeType

if TYPE_CHECKING:
    import uuid


class RoleRepositoryPort(Protocol):
    """Persistence operations for roles and role grants."""

    async def create(self, role: Role) -> Role: ...

    async def get_by_id(self, role_id: str | uuid.UUID) -> Role | None: ...

    async def get_by_name(self, tenant_id: str | uuid.UUID, name: str) -> Role | None: ...

    async def list_by_tenant(
        self, tenant_id: str | uuid.UUID, *, offset: int = 0, limit: int = 20
    ) -> list[Role]: ...

    async def grant_to_user(
        self,
        *,
        user_id: str | uuid.UUID,
        role_id: str | uuid.UUID,
        tenant_id: str | uuid.UUID,
        scope_id: str | uuid.UUID,
        scope_type: ScopeType = ScopeType.TENANT,
    ) -> None: ...

    async def get_roles_for_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID
    ) -> list[str]: ...
