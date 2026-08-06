"""Invitation endpoints — create, accept, and expire invitations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from identity.api.deps import get_invitation_service, require_permission
from identity.core.permissions import INVITATIONS_SEND
from identity.core.tenant_context import TenantContext
from identity.features.invitations.schemas import (
    InvitationAcceptRequest,
    InvitationCreateRequest,
    InvitationResponse,
)
from identity.features.users.schemas import UserResponse
from skyrict_common.schemas import ResponseEnvelope

if TYPE_CHECKING:
    from identity.features.invitations.service import InvitationService

router = APIRouter(prefix="/invitations", tags=["invitations"])

_require_invite = require_permission(INVITATIONS_SEND)


@router.post("", response_model=ResponseEnvelope[InvitationResponse])
async def create_invitation(
    body: InvitationCreateRequest,
    current_user: dict[str, object] = Depends(_require_invite),
    invitation_service: InvitationService = Depends(get_invitation_service),
) -> ResponseEnvelope[InvitationResponse]:
    invitation, token = await invitation_service.create_invitation(
        tenant_id=TenantContext.get(),
        email=body.email,
        role_name=body.role_name,
        created_by_user_id=str(current_user["user_id"]),
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
