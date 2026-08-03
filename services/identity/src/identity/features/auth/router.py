"""Auth endpoints — login, self-service register, email verification, refresh, logout."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Request

from identity.api.deps import (
    get_authn_service,
    get_current_user,
    get_rate_limiter,
    get_token_service,
)
from identity.core.config import settings
from identity.features.auth.schemas import (
    AuthResponse,
    LoginRequest,
    LogoutRequest,
    RegisterRequest,
    RegisterResponse,
    TokenRefreshRequest,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from identity.features.auth.service import AuthenticationService, TokenService
from skyrict_common.schemas import ResponseEnvelope

if TYPE_CHECKING:
    from identity.core.rate_limit import RateLimiter

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=ResponseEnvelope[AuthResponse])
async def login(
    body: LoginRequest,
    request: Request,
    authn: AuthenticationService = Depends(get_authn_service),
) -> ResponseEnvelope[AuthResponse]:
    """Authenticate a user and return tokens."""
    result = await authn.login(
        body,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    user = result.pop("user")
    return ResponseEnvelope(
        data=AuthResponse(**result, user=user),
        message="Login successful",
    )


@router.post("/register", response_model=ResponseEnvelope[RegisterResponse])
async def register(
    body: RegisterRequest,
    request: Request,
    authn: AuthenticationService = Depends(get_authn_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> ResponseEnvelope[RegisterResponse]:
    """Self-service registration: atomically provision a tenant and return a
    verification-pending response (no tokens until the email is verified)."""
    ip_address = request.client.host if request.client else "unknown"
    await limiter.enforce(
        key=f"register:{ip_address}",
        limit=settings.RATE_LIMIT_REGISTER,
        window_seconds=settings.RATE_LIMIT_REGISTER_WINDOW_SECONDS,
    )

    result = await authn.register(
        body,
        ip_address=ip_address,
        user_agent=request.headers.get("user-agent"),
    )
    return ResponseEnvelope(
        data=RegisterResponse(**result),
        message="Registration successful. Check your email to verify your account.",
    )


@router.post("/verify-email", response_model=ResponseEnvelope[VerifyEmailResponse])
async def verify_email(
    body: VerifyEmailRequest,
    authn: AuthenticationService = Depends(get_authn_service),
) -> ResponseEnvelope[VerifyEmailResponse]:
    """Confirm an email address using the token from the registration email."""
    await authn.verify_email(body.token)
    return ResponseEnvelope(
        data=VerifyEmailResponse(verified=True),
        message="Email verified",
    )


@router.post("/refresh", response_model=ResponseEnvelope[AuthResponse])
async def refresh_token(
    body: TokenRefreshRequest,
    token_svc: TokenService = Depends(get_token_service),
) -> ResponseEnvelope[AuthResponse]:
    """Refresh an access token using a refresh token."""
    tokens = await token_svc.refresh_tokens(body.refresh_token)
    return ResponseEnvelope(
        data=AuthResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.expires_in,
        ),
        message="Token refreshed",
    )


@router.post("/logout")
async def logout(
    body: LogoutRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    token_svc: TokenService = Depends(get_token_service),
) -> ResponseEnvelope[None]:
    """Revoke the current session."""
    if body.refresh_token:
        await token_svc.revoke_token(body.refresh_token)
    return ResponseEnvelope(message="Logged out successfully")


@router.post("/introspect")
async def introspect_token(
    body: TokenRefreshRequest,
    token_svc: TokenService = Depends(get_token_service),
) -> ResponseEnvelope[dict[str, Any]]:
    """Introspect a token — return its claims if active."""
    result = await token_svc.introspect(body.refresh_token)
    return ResponseEnvelope(data=result)
