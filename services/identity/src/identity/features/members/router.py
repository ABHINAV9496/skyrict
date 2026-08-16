"""Member management endpoints — list, re-role, remove, and manage sessions."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends

from identity.api.deps import get_member_service, require_permission
from identity.core.tenant_context import TenantContext
from identity.domain.entities import Session
from identity.features.members.schemas import MemberResponse, MemberRoleUpdateRequest
from identity.features.members.service import MemberService
from identity.features.sessions.schemas import (
    SessionListResponse,
    SessionResponse,
    session_to_response,
)
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/members", tags=["members"])

_require_users_read = require_permission("users:read")
_require_users_write = require_permission("users:write")
_require_users_delete = require_permission("users:delete")
_require_sessions_read = require_permission("sessions:read")
_require_sessions_revoke = require_permission("sessions:revoke")


def _session_response(session: Session) -> SessionResponse:
    """Map a session entity to a response (shared mapper for both routers)."""
    return session_to_response(session)


@router.get("", response_model=ResponseEnvelope[list[MemberResponse]])
async def list_members(
    current_user: dict[str, Any] = Depends(_require_users_read),
    member_service: MemberService = Depends(get_member_service),
) -> ResponseEnvelope[list[MemberResponse]]:
    """List all active members in the routed tenant, newest join first."""
    members = await member_service.list_members(
        tenant_id=TenantContext.get(), viewer_id=current_user["user_id"]
    )
    return ResponseEnvelope(data=members, message="Members retrieved")


@router.patch("/{user_id}/role", response_model=ResponseEnvelope[None])
async def change_member_role(
    user_id: UUID,
    body: MemberRoleUpdateRequest,
    current_user: dict[str, Any] = Depends(_require_users_write),
    member_service: MemberService = Depends(get_member_service),
) -> ResponseEnvelope[None]:
    """Change a member's role (single-role replace)."""
    await member_service.change_role(
        tenant_id=TenantContext.get(),
        user_id=user_id,
        role_name=body.role_name,
        actor_user_id=current_user["user_id"],
    )
    return ResponseEnvelope(message="Role updated")


@router.delete("/{user_id}", response_model=ResponseEnvelope[None])
async def remove_member(
    user_id: UUID,
    current_user: dict[str, Any] = Depends(_require_users_delete),
    member_service: MemberService = Depends(get_member_service),
) -> ResponseEnvelope[None]:
    """Remove a member (soft deactivate, logout everywhere, suspend)."""
    await member_service.remove_member(
        tenant_id=TenantContext.get(),
        user_id=user_id,
        actor_user_id=current_user["user_id"],
    )
    return ResponseEnvelope(message="Member removed")


@router.get("/{user_id}/sessions", response_model=ResponseEnvelope[SessionListResponse])
async def list_member_sessions(
    user_id: UUID,
    current_user: dict[str, Any] = Depends(_require_users_read),
    _also_sessions_read: dict[str, Any] = Depends(_require_sessions_read),
    member_service: MemberService = Depends(get_member_service),
) -> ResponseEnvelope[SessionListResponse]:
    """List the member's active sessions in the routed tenant (device audit)."""
    sessions = await member_service.list_member_sessions(
        tenant_id=TenantContext.get(), user_id=user_id
    )
    responses = [_session_response(session) for session in sessions]
    return ResponseEnvelope(
        data=SessionListResponse(sessions=responses, total=len(responses)),
        message="Member sessions retrieved",
    )


@router.delete("/{user_id}/sessions/{session_id}", response_model=ResponseEnvelope[None])
async def revoke_member_session(
    user_id: UUID,
    session_id: UUID,
    current_user: dict[str, Any] = Depends(_require_users_read),
    _also_sessions_revoke: dict[str, Any] = Depends(_require_sessions_revoke),
    member_service: MemberService = Depends(get_member_service),
) -> ResponseEnvelope[None]:
    """Log a member out of a single device (e.g. a lost or suspicious one)."""
    await member_service.revoke_member_session(
        tenant_id=TenantContext.get(),
        user_id=user_id,
        session_id=session_id,
        actor_user_id=current_user["user_id"],
    )
    return ResponseEnvelope(message="Member session revoked")


@router.delete("/{user_id}/sessions", response_model=ResponseEnvelope[None])
async def revoke_all_member_sessions(
    user_id: UUID,
    current_user: dict[str, Any] = Depends(_require_users_read),
    _also_sessions_revoke: dict[str, Any] = Depends(_require_sessions_revoke),
    member_service: MemberService = Depends(get_member_service),
) -> ResponseEnvelope[None]:
    """Log a member out of every device in this workspace."""
    await member_service.revoke_all_member_sessions(
        tenant_id=TenantContext.get(),
        user_id=user_id,
        actor_user_id=current_user["user_id"],
    )
    return ResponseEnvelope(message="Member signed out of all devices")
