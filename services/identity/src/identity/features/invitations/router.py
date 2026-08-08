"""Invitation endpoints — create, accept, and expire invitations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request

from identity.api.deps import get_invitation_service, require_permission
from identity.core.console_urls import security_console_signin_origin
from identity.core.permissions import INVITATIONS_SEND
from identity.core.tenant_context import TenantContext
from identity.core.tenant_resolver import derive_tenant_slug
from identity.features.invitations.schemas import (
    InvitationAcceptRequest,
    InvitationCreateRequest,
    InvitationResponse,
    InvitationSummaryResponse,
)
from identity.features.users.schemas import UserResponse
from skyrict_common.schemas import ResponseEnvelope

if TYPE_CHECKING:
    from identity.features.invitations.service import InvitationService

router = APIRouter(prefix="/invitations", tags=["invitations"])

_require_invite = require_permission(INVITATIONS_SEND)


@router.get("", response_model=ResponseEnvelope[list[InvitationSummaryResponse]])
async def list_invitations(
    _: dict[str, object] = Depends(_require_invite),
    invitation_service: InvitationService = Depends(get_invitation_service),
) -> ResponseEnvelope[list[InvitationSummaryResponse]]:
    """List invitations in the routed tenant (no plaintext tokens exposed)."""
    invitations = await invitation_service.list_invitations(TenantContext.get())
    return ResponseEnvelope(
        data=[InvitationSummaryResponse.model_validate(invitation) for invitation in invitations],
        message="Invitations retrieved",
    )


@router.post("", response_model=ResponseEnvelope[InvitationResponse])
async def create_invitation(
    body: InvitationCreateRequest,
    request: Request,
    current_user: dict[str, object] = Depends(_require_invite),
    invitation_service: InvitationService = Depends(get_invitation_service),
) -> ResponseEnvelope[InvitationResponse]:
    slug = derive_tenant_slug(request)
    base_url = f"{security_console_signin_origin(tenant_slug=slug)}/invite" if slug else None
    invitation, token = await invitation_service.create_invitation(
        tenant_id=TenantContext.get(),
        email=body.email,
        role_name=body.role_name,
        created_by_user_id=str(current_user["user_id"]),
        base_url=base_url,
    )
    assert invitation.id is not None
    return ResponseEnvelope(
        data=InvitationResponse(
            id=invitation.id,
            token=token,
            email=invitation.email,
            role_name=invitation.role_name,
            expires_at=invitation.expires_at,
            used_at=invitation.used_at,
            created_at=invitation.created_at,
        ),
        message="Invitation sent",
    )


@router.post("/accept", response_model=ResponseEnvelope[UserResponse])
async def accept_invitation(
    body: InvitationAcceptRequest,
    invitation_service: InvitationService = Depends(get_invitation_service),
) -> ResponseEnvelope[UserResponse]:
    user = await invitation_service.accept_invitation(
        token=body.token,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
    )
    return ResponseEnvelope(
        data=UserResponse.model_validate(user),
        message="Invitation accepted",
    )


@router.post("/{invitation_id}/expire", response_model=ResponseEnvelope[dict[str, bool]])
async def expire_invitation(
    invitation_id: str,
    current_user: dict[str, object] = Depends(_require_invite),
    invitation_service: InvitationService = Depends(get_invitation_service),
) -> ResponseEnvelope[dict[str, bool]]:
    await invitation_service.expire_invitation(invitation_id, TenantContext.get())
    return ResponseEnvelope(data={"expired": True}, message="Invitation expired")
