"""Organization endpoints — CRUD for tenants."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from identity.api.deps import get_current_user, get_tenant_service
from identity.features.organizations.schemas import TenantCreateRequest, TenantResponse
from identity.features.organizations.service import TenantService
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/me", response_model=ResponseEnvelope[TenantResponse])
async def get_my_organization(
    current_user: dict[str, Any] = Depends(get_current_user),
    tenant_svc: TenantService = Depends(get_tenant_service),
) -> ResponseEnvelope[TenantResponse]:
    """Get the current user's organization."""
    from identity.core.tenant_context import TenantContext

    tenant = await tenant_svc.get_organization(TenantContext.get())
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
