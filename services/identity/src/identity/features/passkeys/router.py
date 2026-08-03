"""Passkey (WebAuthn) endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from identity.features.dependencies import get_current_user, get_passkey_service
from identity.features.passkeys.service import PasskeyService
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/passkeys", tags=["passkeys"])


@router.post("/register/start")
async def start_passkey_registration(
    current_user: dict[str, Any] = Depends(get_current_user),
    passkey_svc: PasskeyService = Depends(get_passkey_service),
) -> ResponseEnvelope[dict[str, Any]]:
    """Start passkey registration — returns WebAuthn creation options."""
    import uuid

    options = await passkey_svc.start_registration(uuid.UUID(current_user["user_id"]))
    return ResponseEnvelope(data=options)


@router.post("/register/complete")
async def complete_passkey_registration(
    credential: dict[str, Any],
    current_user: dict[str, Any] = Depends(get_current_user),
    passkey_svc: PasskeyService = Depends(get_passkey_service),
) -> ResponseEnvelope[dict[str, Any]]:
    """Complete passkey registration after browser ceremony."""
    import uuid

    result = await passkey_svc.complete_registration(uuid.UUID(current_user["user_id"]), credential)
    return ResponseEnvelope(data=result, message="Passkey registered")


@router.post("/authenticate/start")
async def start_passkey_authentication(
    email: str,
    passkey_svc: PasskeyService = Depends(get_passkey_service),
) -> ResponseEnvelope[dict[str, Any]]:
    """Start passkey authentication — returns WebAuthn request options."""
    options = await passkey_svc.start_authentication(email)
    return ResponseEnvelope(data=options)


@router.post("/authenticate/complete")
async def complete_passkey_authentication(
    credential: dict[str, Any],
    passkey_svc: PasskeyService = Depends(get_passkey_service),
) -> ResponseEnvelope[dict[str, Any]]:
    """Complete passkey authentication after browser ceremony."""
    result = await passkey_svc.complete_authentication(credential)
    return ResponseEnvelope(data=result, message="Passkey authentication successful")
