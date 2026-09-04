"""MFA endpoints - TOTP setup, verification, disable, and owner-assisted reset."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Request

from identity.api.deps import (
    get_current_user,
    get_mfa_attempt_store,
    get_mfa_service,
    get_rate_limiter,
    require_permission,
)
from identity.core.client_ip import client_ip
from identity.core.config import settings
from identity.core.rate_limit import RateLimiter
from identity.features.mfa.schemas import (
    MFABackupCodesResponse,
    MFADisableRequest,
    MFAResetRequest,
    MFASetupResponse,
    MFAVerifyRequest,
    MFAVerifyResponse,
)
from skyrict_common.exceptions import RateLimitExceededError
from skyrict_common.schemas import ResponseEnvelope

if TYPE_CHECKING:
    from identity.features.mfa.attempt_store import MFAAttemptStore
    from identity.features.mfa.service import MFAService

router = APIRouter(prefix="/mfa", tags=["mfa"])

_require_mfa_manage = require_permission("mfa:manage")


@router.post("/setup", response_model=ResponseEnvelope[MFASetupResponse])
async def setup_mfa(
    current_user: dict[str, Any] = Depends(get_current_user),
    mfa_service: MFAService = Depends(get_mfa_service),
) -> ResponseEnvelope[MFASetupResponse]:
    """Initiate MFA setup - returns TOTP secret, otpauth URI, and 10 backup codes."""
    result = await mfa_service.setup_totp(current_user["user_id"])
    return ResponseEnvelope(data=MFASetupResponse(**result), message="MFA setup initiated")


@router.post("/verify", response_model=ResponseEnvelope[MFAVerifyResponse])
async def verify_mfa(
    body: MFAVerifyRequest,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
    mfa_service: MFAService = Depends(get_mfa_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
    attempt_store: MFAAttemptStore = Depends(get_mfa_attempt_store),
) -> ResponseEnvelope[MFAVerifyResponse]:
    """Verify a TOTP code (or backup code) and mark MFA as enabled.

    Brute-force guarded with per-IP/per-user rate limits plus a per-user
    failed-attempt lockout. The attempt counter is incremented before the
    check and cleared only on success, so every wrong guess counts and the
    user is locked out for ``MFA_ENROLL_LOCKOUT_SECONDS`` once
    ``MFA_ENROLL_MAX_ATTEMPTS`` is exceeded.
    """
    user_id = current_user["user_id"]
    ip_address = client_ip(request)

    await limiter.enforce(
        key=f"mfa-enroll-ip:{ip_address}",
        limit=settings.RATE_LIMIT_MFA_ENROLL,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )
    await limiter.enforce(
        key=f"mfa-enroll-user:{user_id}",
        limit=settings.RATE_LIMIT_MFA_ENROLL,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )

    attempts = await attempt_store.increment_attempts(
        user_id,
        ttl_seconds=settings.MFA_ENROLL_LOCKOUT_SECONDS,
    )
    if attempts > settings.MFA_ENROLL_MAX_ATTEMPTS:
        raise RateLimitExceededError("Too many attempts. Try again later.")

    method = await mfa_service.enable_mfa(user_id, body.code)
    await attempt_store.clear(user_id)
    return ResponseEnvelope(
        data=MFAVerifyResponse(verified=True, method=method),
        message="MFA verified and enabled",
    )


@router.post("/backup-codes", response_model=ResponseEnvelope[MFABackupCodesResponse])
async def rotate_backup_codes(
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user),
    mfa_service: MFAService = Depends(get_mfa_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> ResponseEnvelope[MFABackupCodesResponse]:
    """Generate a fresh set of backup codes; the previous set stops working.

    The TOTP secret is untouched, so an enrolled authenticator keeps working.
    Rate-limited per user so the endpoint can't be used to churn through
    regenerations.
    """
    user_id = current_user["user_id"]
    await limiter.enforce(
        key=f"mfa-backup-codes-user:{user_id}",
        limit=settings.RATE_LIMIT_MFA_BACKUP_CODES,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )

    codes = await mfa_service.rotate_backup_codes(user_id)
    return ResponseEnvelope(
        data=MFABackupCodesResponse(backup_codes=codes),
        message="Backup codes regenerated",
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
