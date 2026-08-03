"""MFA endpoints — not yet implemented (explicit 501)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/mfa", tags=["mfa"])


@router.post("/setup")
async def setup_mfa() -> None:
    """Initiate MFA setup — returns TOTP secret and backup codes."""
    raise HTTPException(status_code=501, detail="MFA is not yet implemented")


@router.post("/verify")
async def verify_mfa(code: str) -> None:
    """Verify a TOTP code during setup or login."""
    raise HTTPException(status_code=501, detail="MFA is not yet implemented")


@router.post("/enable")
async def enable_mfa(secret: str, code: str) -> None:
    """Enable MFA after verifying the initial TOTP code."""
    raise HTTPException(status_code=501, detail="MFA is not yet implemented")


@router.post("/disable")
async def disable_mfa(password: str) -> None:
    """Disable MFA after password confirmation."""
    raise HTTPException(status_code=501, detail="MFA is not yet implemented")
