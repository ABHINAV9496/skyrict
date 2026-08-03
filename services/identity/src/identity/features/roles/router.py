"""Role endpoints — custom role creation and listing (tenant-scoped)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from identity.api.deps import get_roles_service, require_permission
from identity.core.tenant_context import TenantContext
from identity.features.roles.schemas import RoleCreateRequest, RoleResponse
from skyrict_common.schemas import ResponseEnvelope

if TYPE_CHECKING:
    from identity.features.roles.service import RoleManagementService

router = APIRouter(prefix="/roles", tags=["roles"])

# Module-level dependency singletons so the permission factory runs once at
# import time, not in every route's argument defaults (B008).
_require_roles_write = require_permission("roles:write")
_require_roles_read = require_permission("roles:read")


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
