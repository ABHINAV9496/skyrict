"""MFA endpoints — setup, verify, backup codes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from identity.features.dependencies import get_current_user, get_mfa_service
from identity.features.mfa.service import MFAService
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/mfa", tags=["mfa"])


@router.post("/setup")
async def setup_mfa(
    current_user: dict[str, Any] = Depends(get_current_user),
    mfa_svc: MFAService = Depends(get_mfa_service),
) -> ResponseEnvelope[dict[str, Any]]:
    """Initiate MFA setup — returns TOTP secret and backup codes."""
    import uuid

    result = await mfa_svc.setup_totp(uuid.UUID(current_user["user_id"]))
    return ResponseEnvelope(data=result, message="MFA setup initiated")


@router.post("/verify")
async def verify_mfa(
    code: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    mfa_svc: MFAService = Depends(get_mfa_service),
) -> ResponseEnvelope[dict[str, Any]]:
    """Verify a TOTP code during setup or login."""
    import uuid

    valid = await mfa_svc.verify_totp(uuid.UUID(current_user["user_id"]), code)
    return ResponseEnvelope(data={"valid": valid}, message="MFA code verified")


@router.post("/enable")
async def enable_mfa(
    secret: str,
    code: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    mfa_svc: MFAService = Depends(get_mfa_service),
) -> ResponseEnvelope[None]:
    """Enable MFA after verifying the initial TOTP code."""
    import uuid

    await mfa_svc.enable_mfa(uuid.UUID(current_user["user_id"]), secret, code)
    return ResponseEnvelope(message="MFA enabled successfully")


@router.post("/disable")
async def disable_mfa(
    password: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    mfa_svc: MFAService = Depends(get_mfa_service),
) -> ResponseEnvelope[None]:
    """Disable MFA after password confirmation."""
    import uuid

    await mfa_svc.disable_mfa(uuid.UUID(current_user["user_id"]), password)
    return ResponseEnvelope(message="MFA disabled")
