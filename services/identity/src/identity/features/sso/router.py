"""SSO endpoints — SAML/OIDC identity provider callbacks, not yet implemented."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/sso", tags=["sso"])


@router.post("/oidc/start")
async def start_oidc(provider: str, redirect_uri: str) -> None:
    """Start OIDC SSO flow — returns authorization URL."""
    raise HTTPException(status_code=501, detail="SSO is not yet implemented")


@router.post("/oidc/callback")
async def oidc_callback(code: str, state: str) -> None:
    """Handle OIDC callback — exchange code for tokens, return session."""
    raise HTTPException(status_code=501, detail="SSO is not yet implemented")


@router.post("/saml/start")
async def start_saml(provider: str) -> None:
    """Start SAML SSO flow."""
    raise HTTPException(status_code=501, detail="SSO is not yet implemented")


@router.post("/saml/callback")
async def saml_callback(saml_response: str) -> None:
    """Handle SAML callback."""
    raise HTTPException(status_code=501, detail="SSO is not yet implemented")
