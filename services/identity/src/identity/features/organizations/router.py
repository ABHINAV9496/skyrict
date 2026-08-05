"""Organization endpoints — tenant CRUD and security settings."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends

from identity.api.deps import get_current_user, get_tenant_service, require_permission
from identity.core.tenant_context import get_current_tenant
from identity.features.organizations.schemas import (
    TenantCreateRequest,
    TenantResponse,
    TenantSettingsUpdateRequest,
)
from identity.features.organizations.service import TenantService
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/organizations", tags=["organizations"])

# Security-policy endpoints live under /tenants and require tenants:write.
settings_router = APIRouter(prefix="/tenants", tags=["organizations"])

_require_tenants_write = require_permission("tenants:write")


@router.get("/me", response_model=ResponseEnvelope[TenantResponse])
async def get_my_organization(
    current_user: dict[str, Any] = Depends(get_current_user),
    tenant_svc: TenantService = Depends(get_tenant_service),
    tenant_id: str = Depends(get_current_tenant),
) -> ResponseEnvelope[TenantResponse]:
    """Get the current user's organization."""
    tenant = await tenant_svc.get_organization(tenant_id)
    return ResponseEnvelope(data=TenantResponse.model_validate(tenant))


@router.post("", response_model=ResponseEnvelope[TenantResponse])
async def create_organization(
    body: TenantCreateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    tenant_svc: TenantService = Depends(get_tenant_service),
) -> ResponseEnvelope[TenantResponse]:
    """Create a new organization."""
    tenant = await tenant_svc.create_organization(body)
    return ResponseEnvelope(
        data=TenantResponse.model_validate(tenant), message="Organization created"
    )


@settings_router.patch("/{tenant_id}/settings", response_model=ResponseEnvelope[TenantResponse])
async def update_tenant_settings(
    tenant_id: UUID,
    body: TenantSettingsUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    _permission: dict[str, Any] = Depends(_require_tenants_write),
    tenant_svc: TenantService = Depends(get_tenant_service),
) -> ResponseEnvelope[TenantResponse]:
    """Update tenant security settings (requires ``tenants:write``)."""
    tenant = await tenant_svc.update_settings(tenant_id, body)
    return ResponseEnvelope(
        data=TenantResponse.model_validate(tenant),
        message="Organization settings updated",
    )
