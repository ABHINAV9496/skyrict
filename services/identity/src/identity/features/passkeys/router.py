"""Passkey (WebAuthn) endpoints - not yet implemented (explicit 501)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/passkeys", tags=["passkeys"])


@router.post("/register/start")
async def start_passkey_registration() -> None:
    """Start passkey registration - returns WebAuthn creation options."""
    raise HTTPException(status_code=501, detail="Passkeys are not yet implemented")


@router.post("/register/complete")
async def complete_passkey_registration(credential: dict[str, object]) -> None:
    """Complete passkey registration after browser ceremony."""
    raise HTTPException(status_code=501, detail="Passkeys are not yet implemented")


@router.post("/authenticate/start")
async def start_passkey_authentication(email: str) -> None:
    """Start passkey authentication - returns WebAuthn request options."""
    raise HTTPException(status_code=501, detail="Passkeys are not yet implemented")


@router.post("/authenticate/complete")
async def complete_passkey_authentication(credential: dict[str, object]) -> None:
    """Complete passkey authentication after browser ceremony."""
    raise HTTPException(status_code=501, detail="Passkeys are not yet implemented")
