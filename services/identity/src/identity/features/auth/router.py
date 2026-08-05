"""Auth endpoints — login, onboarding wizard, refresh, logout, introspect."""

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
from identity.core.constants import (
    SIGNUP_CHECK_LIMIT_KEY,
    SIGNUP_CODE_IP_LIMIT_KEY,
    SIGNUP_CODE_LIMIT_KEY,
    SIGNUP_START_LIMIT_KEY,
    SIGNUP_VERIFY_LIMIT_KEY,
)
from identity.features.auth.schemas import (
    AuthResponse,
    CheckEmailRequest,
    CheckEmailResponse,
    CheckSlugRequest,
    CheckSlugResponse,
    CreateOrganizationRequest,
    CreateOrganizationResponse,
    LoginRequest,
    LogoutRequest,
    SendCodeRequest,
    SendCodeResponse,
    SetPasswordRequest,
    SetPasswordResponse,
    SignupStartRequest,
    SignupStartResponse,
    TokenRefreshRequest,
    VerifyCodeRequest,
    VerifyCodeResponse,
)
from identity.features.auth.service import AuthenticationService, TokenService
from skyrict_common.schemas import ResponseEnvelope

if TYPE_CHECKING:
    from identity.core.rate_limit import RateLimiter

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=ResponseEnvelope[AuthResponse])
async def login(
    body: LoginRequest,
    request: Request,
    authn: AuthenticationService = Depends(get_authn_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> ResponseEnvelope[AuthResponse]:
    """Authenticate a user and return tokens.

    Rate-limited per (source IP, account) — ``RATE_LIMIT_LOGIN`` attempts per
    ``RATE_LIMIT_WINDOW_SECONDS`` — to blunt brute-force and credential-
    stuffing against the highest-value endpoint. The limiter fails open when
    Redis is unavailable so a Redis outage never becomes a login outage.
    """
    ip_address = _client_ip(request)
    await limiter.enforce(
        key=f"login:{ip_address}:{body.email.lower()}",
        limit=settings.RATE_LIMIT_LOGIN,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )

    result = await authn.login(
        body,
        ip_address=ip_address,
        user_agent=request.headers.get("user-agent"),
    )
    user = result.pop("user")
    return ResponseEnvelope(
        data=AuthResponse(**result, user=user),
        message="Login successful",
    )


@router.post("/signup/start", response_model=ResponseEnvelope[SignupStartResponse])
async def signup_start(
    body: SignupStartRequest,
    request: Request,
    authn: AuthenticationService = Depends(get_authn_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> ResponseEnvelope[SignupStartResponse]:
    """Gate the wizard: server-side Turnstile verification + per-IP throttling."""
    ip_address = _client_ip(request)
    await limiter.enforce(
        key=f"{SIGNUP_START_LIMIT_KEY}:{ip_address}",
        limit=settings.SIGNUP_START_RATE_LIMIT,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )
    result = await authn.signup_start(email=body.email, turnstile_token=body.turnstile_token)
    return ResponseEnvelope(data=SignupStartResponse(**result))


@router.post("/signup/send-code", response_model=ResponseEnvelope[SendCodeResponse])
async def signup_send_code(
    body: SendCodeRequest,
    request: Request,
    authn: AuthenticationService = Depends(get_authn_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> ResponseEnvelope[SendCodeResponse]:
    """Send a 6-digit OTP to the address (throttled per email and per IP)."""
    ip_address = _client_ip(request)
    email_key = body.email.lower()
    await limiter.enforce(
        key=f"{SIGNUP_CODE_LIMIT_KEY}:{email_key}",
        limit=settings.SIGNUP_CODE_RATE_LIMIT,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )
    await limiter.enforce(
        key=f"{SIGNUP_CODE_IP_LIMIT_KEY}:{ip_address}",
        limit=settings.SIGNUP_CODE_RATE_LIMIT,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )
    result = await authn.signup_send_code(email=body.email)
    return ResponseEnvelope(data=SendCodeResponse(**result))


@router.post("/signup/verify-code", response_model=ResponseEnvelope[VerifyCodeResponse])
async def signup_verify_code(
    body: VerifyCodeRequest,
    request: Request,
    authn: AuthenticationService = Depends(get_authn_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> ResponseEnvelope[VerifyCodeResponse]:
    """Check an OTP; on success return an opaque single-use verification token."""
    await limiter.enforce(
        key=f"{SIGNUP_VERIFY_LIMIT_KEY}:{body.email.lower()}",
        limit=settings.SIGNUP_VERIFY_RATE_LIMIT,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )
    result = await authn.signup_verify_code(email=body.email, code=body.code)
    return ResponseEnvelope(data=VerifyCodeResponse(**result))


@router.post("/signup/password", response_model=ResponseEnvelope[SetPasswordResponse])
async def signup_password(
    body: SetPasswordRequest,
    authn: AuthenticationService = Depends(get_authn_service),
) -> ResponseEnvelope[SetPasswordResponse]:
    """Set the password for the wizard session bound to the verification token."""
    result = await authn.signup_set_password(
        email=body.email,
        verification_token=body.verification_token,
        password=body.password,
    )
    return ResponseEnvelope(data=SetPasswordResponse(**result))


@router.post("/signup/check-email", response_model=ResponseEnvelope[CheckEmailResponse])
async def signup_check_email(
    body: CheckEmailRequest,
    request: Request,
    authn: AuthenticationService = Depends(get_authn_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> ResponseEnvelope[CheckEmailResponse]:
    """Expose email availability for the account step (rate-limited per IP)."""
    ip_address = _client_ip(request)
    await limiter.enforce(
        key=f"{SIGNUP_CHECK_LIMIT_KEY}:{ip_address}",
        limit=settings.SIGNUP_CHECK_RATE_LIMIT,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )
    result = await authn.signup_check_email(email=body.email)
    return ResponseEnvelope(data=CheckEmailResponse(**result))


@router.post("/signup/check-slug", response_model=ResponseEnvelope[CheckSlugResponse])
async def signup_check_slug(
    body: CheckSlugRequest,
    request: Request,
    authn: AuthenticationService = Depends(get_authn_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> ResponseEnvelope[CheckSlugResponse]:
    """Expose workspace slug availability for the organization step."""
    ip_address = _client_ip(request)
    await limiter.enforce(
        key=f"{SIGNUP_CHECK_LIMIT_KEY}:{ip_address}",
        limit=settings.SIGNUP_CHECK_RATE_LIMIT,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )
    result = await authn.signup_check_slug(slug=body.slug)
    return ResponseEnvelope(data=CheckSlugResponse(**result))


@router.post("/signup/organization", response_model=ResponseEnvelope[CreateOrganizationResponse])
async def signup_organization(
    body: CreateOrganizationRequest,
    request: Request,
    authn: AuthenticationService = Depends(get_authn_service),
) -> ResponseEnvelope[CreateOrganizationResponse]:
    """Provision the tenant, roles, and verified owner in one transaction."""
    result = await authn.signup_create_organization(
        body,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ResponseEnvelope(
        data=CreateOrganizationResponse(**result),
        message="Your organization is ready",
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
