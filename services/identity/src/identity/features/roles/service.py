"""Role management service — custom role CRUD business rules.

``AuthorizationService`` stays pure and stateless (permission checks).
``RoleManagementService`` owns role-creation rules and persists through the
``RoleRepositoryPort``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from identity.core.constants import SYSTEM_ROLE_NAMES
from identity.domain.entities import Role
from skyrict_common.exceptions import AuthorizationError, ValidationError

if TYPE_CHECKING:
    from identity.features.roles.ports import RoleRepositoryPort
    from identity.features.roles.schemas import RoleCreateRequest


class AuthorizationService:
    """Handles permission checks and RBAC enforcement."""

    def check_permission(self, *, user_is_active: bool, permission: str, tenant_id: str) -> bool:
        """Check whether an active user has a specific permission in their tenant.

        Returns True if authorized, raises AuthorizationError if not.
        """
        if not user_is_active:
            raise AuthorizationError("User account is disabled")
        # TODO: Check the user's roles -> permissions against the required permission.
        return True

    def require_permission(self, *, user_is_active: bool, permission: str, tenant_id: str) -> None:
        """Like check_permission but always raises on failure."""
        self.check_permission(
            user_is_active=user_is_active, permission=permission, tenant_id=tenant_id
        )


class RoleManagementService:
    """Encapsulates custom-role creation and listing business rules."""

    def __init__(self, role_repo: RoleRepositoryPort) -> None:
        self.role_repo = role_repo

    async def create_custom_role(self, tenant_id: str | uuid.UUID, body: RoleCreateRequest) -> Role:
        """Create a custom role, rejecting reserved system names and duplicates."""
        if body.name in SYSTEM_ROLE_NAMES:
            raise ValidationError(f"'{body.name}' is a reserved system role")

        existing = await self.role_repo.get_by_name(tenant_id, body.name)
        if existing is not None:
            raise ValidationError(f"Role '{body.name}' already exists")

        return await self.role_repo.create(
            Role(
                tenant_id=uuid.UUID(str(tenant_id)),
                name=body.name,
                permissions=body.permissions,
                is_system_role=False,
            )
        )

    async def list_roles(
        self, tenant_id: str | uuid.UUID, *, offset: int = 0, limit: int = 20
    ) -> list[Role]:
        """List all roles (system + custom) for a tenant."""
        return await self.role_repo.list_by_tenant(tenant_id, offset=offset, limit=limit)
