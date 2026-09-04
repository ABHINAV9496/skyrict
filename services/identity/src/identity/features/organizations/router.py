"""Organization endpoints - tenant CRUD."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from identity.api.deps import get_current_user, get_tenant_service
from identity.core.tenant_context import get_current_tenant
from identity.features.organizations.schemas import TenantCreateRequest, TenantResponse
from identity.features.organizations.service import TenantService
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/me", response_model=ResponseEnvelope[TenantResponse])
async def get_my_organization(
    current_user: dict[str, Any] = Depends(get_current_user),
    tenant_svc: TenantService = Depends(get_tenant_service),
    tenant_id: str = Depends(get_current_tenant),
) -> ResponseEnvelope[TenantResponse]:
    """Get the current user's organization."""
    tenant = await tenant_svc.get_organization(tenant_id)
    return ResponseEnvelope(data=TenantResponse.model_validate(tenant))


@router.post("/me/onboarding/complete", response_model=ResponseEnvelope[TenantResponse])
async def complete_onboarding(
    current_user: dict[str, Any] = Depends(get_current_user),
    tenant_svc: TenantService = Depends(get_tenant_service),
    tenant_id: str = Depends(get_current_tenant),
) -> ResponseEnvelope[TenantResponse]:
    """Mark the current organization's onboarding wizard as complete."""
    tenant = await tenant_svc.complete_onboarding(tenant_id)
    return ResponseEnvelope(
        data=TenantResponse.model_validate(tenant), message="Onboarding completed"
    )


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
