"""Role endpoints — custom role CRUD and scoped assignment (tenant-scoped)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from identity.api.deps import get_current_user, get_role_repo, get_roles_service, require_permission
from identity.core.permissions import PERMISSION_MODULES
from identity.core.tenant_context import TenantContext
from identity.domain.entities import ScopeType
from identity.features.roles.repository import RoleRepository
from identity.features.roles.schemas import (
    MyRolesResponse,
    PermissionCatalogResponse,
    PermissionModule,
    PermissionResponse,
    RoleCreateRequest,
    RoleResponse,
)
from skyrict_common.schemas import ResponseEnvelope

if TYPE_CHECKING:
    from identity.features.roles.service import RoleManagementService

router = APIRouter(prefix="/roles", tags=["roles"])

# Module-level dependency singletons so the permission factory runs once at
# import time, not in every route's argument defaults (B008).
_require_roles_write = require_permission("roles:write")
_require_roles_read = require_permission("roles:read")


class RoleUpdateRequest(BaseModel):
    """PATCH /roles/{id} — update a custom role's name and/or permissions."""

    name: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[a-z0-9_-]+$")
    permission_keys: list[str] | None = None

    model_config = ConfigDict(extra="forbid")


class RoleAssignRequest(BaseModel):
    """POST /roles/{id}/assign — grant a role to a user within a scope."""

    user_id: UUID
    scope_type: ScopeType = ScopeType.TENANT
    scope_id: UUID | None = None


@router.post("", response_model=ResponseEnvelope[RoleResponse])
async def create_role(
    body: RoleCreateRequest,
    _: dict[str, object] = Depends(_require_roles_write),
    roles_service: RoleManagementService = Depends(get_roles_service),
) -> ResponseEnvelope[RoleResponse]:
    """Create a custom (non-system) role in the routed tenant."""
    role = await roles_service.create_custom_role(TenantContext.get(), body)
    return ResponseEnvelope(data=RoleResponse.model_validate(role), message="Role created")


@router.get("", response_model=ResponseEnvelope[list[RoleResponse]])
async def list_roles(
    _: dict[str, object] = Depends(_require_roles_read),
    roles_service: RoleManagementService = Depends(get_roles_service),
) -> ResponseEnvelope[list[RoleResponse]]:
    """List all roles in the routed tenant."""
    roles = await roles_service.list_roles(TenantContext.get())
    return ResponseEnvelope(
        data=[RoleResponse.model_validate(role) for role in roles],
        message="Roles retrieved",
    )


@router.get("/me", response_model=ResponseEnvelope[MyRolesResponse])
async def get_my_roles(
    current_user: dict[str, Any] = Depends(get_current_user),
    role_repo: RoleRepository = Depends(get_role_repo),
) -> ResponseEnvelope[MyRolesResponse]:
    """Return the current user's roles and effective permissions in this tenant."""
    user_id = current_user["user_id"]
    tenant_id = current_user["tenant_id"]
    roles = await role_repo.get_roles_for_user(user_id, tenant_id)
    permissions = await role_repo.get_permissions_for_user(user_id, tenant_id)
    return ResponseEnvelope(
        data=MyRolesResponse(roles=roles, permissions=sorted(permissions)),
        message="Roles retrieved",
    )


@router.get("/{role_id}", response_model=ResponseEnvelope[RoleResponse])
async def get_role(
    role_id: UUID,
    _: dict[str, object] = Depends(_require_roles_read),
    roles_service: RoleManagementService = Depends(get_roles_service),
) -> ResponseEnvelope[RoleResponse]:
    """Get a single role in the routed tenant (404 when absent or foreign)."""
    role = await roles_service.get_role(TenantContext.get(), role_id)
    return ResponseEnvelope(data=RoleResponse.model_validate(role), message="Role retrieved")


@router.patch("/{role_id}", response_model=ResponseEnvelope[RoleResponse])
async def update_role(
    role_id: UUID,
    body: RoleUpdateRequest,
    _: dict[str, object] = Depends(_require_roles_write),
    roles_service: RoleManagementService = Depends(get_roles_service),
) -> ResponseEnvelope[RoleResponse]:
    """Update a custom role in the routed tenant."""
    role = await roles_service.update_role(
        TenantContext.get(),
        role_id,
        name=body.name,
        permissions=body.permission_keys,
    )
    return ResponseEnvelope(data=RoleResponse.model_validate(role), message="Role updated")


@router.delete("/{role_id}", response_model=ResponseEnvelope[None])
async def delete_role(
    role_id: UUID,
    _: dict[str, object] = Depends(_require_roles_write),
    roles_service: RoleManagementService = Depends(get_roles_service),
) -> ResponseEnvelope[None]:
    """Delete a custom role (system roles are protected)."""
    await roles_service.delete_role(TenantContext.get(), role_id)
    return ResponseEnvelope(message="Role deleted")


@router.post("/{role_id}/assign", response_model=ResponseEnvelope[None])
async def assign_role(
    role_id: UUID,
    body: RoleAssignRequest,
    _: dict[str, object] = Depends(_require_roles_write),
    roles_service: RoleManagementService = Depends(get_roles_service),
) -> ResponseEnvelope[None]:
    """Assign a role to a user within a scope in the routed tenant."""
    await roles_service.assign_role(
        TenantContext.get(),
        role_id,
        user_id=body.user_id,
        scope_type=body.scope_type,
        scope_id=body.scope_id,
    )
    return ResponseEnvelope(message="Role assigned")


# --- Permissions catalog endpoint (public, un-gated) ---

permissions_router = APIRouter(prefix="/permissions", tags=["permissions"])


def _permission_description(module_label: str, perm_key: str) -> str:
    """Generate human-readable description from module label and permission key."""
    action = perm_key.split(":")[-1].replace(".", " ")
    return f"{module_label}: {action}"


@permissions_router.get("", response_model=ResponseEnvelope[PermissionCatalogResponse])
async def get_permissions_catalog() -> ResponseEnvelope[PermissionCatalogResponse]:
    """Return the full platform permission catalog grouped by module."""
    modules: list[PermissionModule] = []
    for module_key, module_label, perm_keys in PERMISSION_MODULES:
        permissions = [
            PermissionResponse(key=key, description=_permission_description(module_label, key))
            for key in perm_keys
        ]
        modules.append(
            PermissionModule(key=module_key, label=module_label, permissions=permissions)
        )
    return ResponseEnvelope(
        data=PermissionCatalogResponse(modules=modules), message="Permission catalog retrieved"
    )
