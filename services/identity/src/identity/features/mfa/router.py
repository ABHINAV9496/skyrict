"""MFA endpoints — TOTP setup, verification, disable, and owner-assisted reset."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends

from identity.api.deps import (
    get_current_user,
    get_mfa_service,
    require_permission,
)
from identity.features.mfa.schemas import (
    MFADisableRequest,
    MFAResetRequest,
    MFASetupResponse,
    MFAVerifyRequest,
    MFAVerifyResponse,
)
from skyrict_common.schemas import ResponseEnvelope

if TYPE_CHECKING:
    from identity.features.mfa.service import MFAService

router = APIRouter(prefix="/mfa", tags=["mfa"])

_require_mfa_manage = require_permission("mfa:manage")


@router.post("/setup", response_model=ResponseEnvelope[MFASetupResponse])
async def setup_mfa(
    current_user: dict[str, Any] = Depends(get_current_user),
    mfa_service: MFAService = Depends(get_mfa_service),
) -> ResponseEnvelope[MFASetupResponse]:
    """Initiate MFA setup — returns TOTP secret, otpauth URI, and 10 backup codes."""
    result = await mfa_service.setup_totp(current_user["user_id"])
    return ResponseEnvelope(data=MFASetupResponse(**result), message="MFA setup initiated")


@router.post("/verify", response_model=ResponseEnvelope[MFAVerifyResponse])
async def verify_mfa(
    body: MFAVerifyRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    mfa_service: MFAService = Depends(get_mfa_service),
) -> ResponseEnvelope[MFAVerifyResponse]:
    """Verify a TOTP code (or backup code) and mark MFA as enabled."""
    method = await mfa_service.enable_mfa(current_user["user_id"], body.code)
    return ResponseEnvelope(
        data=MFAVerifyResponse(verified=True, method=method),
        message="MFA verified and enabled",
    )


@router.post("/disable")
async def disable_mfa(
    body: MFADisableRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    mfa_service: MFAService = Depends(get_mfa_service),
) -> ResponseEnvelope[None]:
    """Disable MFA after password confirmation."""
    await mfa_service.disable_mfa(current_user["user_id"], body.password)
    return ResponseEnvelope(message="MFA disabled")


@router.post("/reset")
async def reset_mfa(
    body: MFAResetRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    _permission: dict[str, Any] = Depends(_require_mfa_manage),
    mfa_service: MFAService = Depends(get_mfa_service),
) -> ResponseEnvelope[None]:
    """Owner-assisted reset of a locked-out user's MFA."""
    await mfa_service.reset_mfa_by_owner(current_user["user_id"], body.user_id)
    return ResponseEnvelope(message="MFA reset")
