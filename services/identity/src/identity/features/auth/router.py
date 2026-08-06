"""Auth endpoints â€” login, onboarding wizard, refresh, logout, introspect."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Request

from identity.api.deps import (
    get_audit_service,
    get_authn_service,
    get_current_user,
    get_mfa_challenge_store,
    get_mfa_service,
    get_rate_limiter,
    get_token_service,
    get_user_repo,
)
from identity.core.config import settings
from identity.core.constants import (
    LOGIN_FAILED_MESSAGE,
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
    MfaChallengeVerifyRequest,
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
from skyrict_common.exceptions import AuthenticationError
from skyrict_common.schemas import ResponseEnvelope

if TYPE_CHECKING:
    from identity.core.rate_limit import RateLimiter
    from identity.features.audit.service import AuditService
    from identity.features.auth.mfa_challenge_store import MfaChallengeStore
    from identity.features.mfa.service import MFAService
    from identity.features.users.repository import UserRepository

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
    """
    Authenticate a user and return tokens.

    Rate-limited per (source IP, account) â€” ``RATE_LIMIT_LOGIN`` attempts per
    ``RATE_LIMIT_WINDOW_SECONDS`` â€” to blunt brute-force and credential-
    stuffing against the highest-value endpoint. The limiter fails open when
    Redis is unavailable so a Redis outage never becomes a login outage.
    """
    ip_address = _client_ip(request)
    await limiter.enforce(
        key=f"login:{ip_address}:{body.email.lower()}",
        limit=settings.RATE_LIMIT_LOGIN,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )

    await limiter.enforce(
        key=f"login-ip:{ip_address}",
        limit=settings.RATE_LIMIT_LOGIN_IP,
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


@router.post("/mfa/verify", response_model=ResponseEnvelope[AuthResponse])
async def verify_mfa_challenge(
    body: MfaChallengeVerifyRequest,
    request: Request,
    authn: AuthenticationService = Depends(get_authn_service),
    mfa_service: MFAService = Depends(get_mfa_service),
    user_repo: UserRepository = Depends(get_user_repo),
    audit_service: AuditService = Depends(get_audit_service),
    challenge_store: MfaChallengeStore = Depends(get_mfa_challenge_store),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> ResponseEnvelope[AuthResponse]:
    """Redeem a login mfaToken with a TOTP/backup code and issue the token pair."""

    ip_address = _client_ip(request)
    await limiter.enforce(
        key=f"mfa-verify-ip:{ip_address}",
        limit=settings.RATE_LIMIT_MFA_VERIFY,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )
    await limiter.enforce(
        key=f"mfa-verify-token:{body.mfa_token}",
        limit=settings.RATE_LIMIT_MFA_VERIFY,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    )

    challenge = await challenge_store.get(body.mfa_token)
    if challenge is None:
        raise AuthenticationError(LOGIN_FAILED_MESSAGE)

    attempts = await challenge_store.increment_attempts(body.mfa_token)
    if attempts > settings.MFA_CHALLENGE_MAX_ATTEMPTS:
        await challenge_store.consume(body.mfa_token)
        raise AuthenticationError(LOGIN_FAILED_MESSAGE)

    user = await user_repo.get_by_id(uuid.UUID(challenge["user_id"]))
    if user is None or not user.is_active or not user.is_verified:
        await challenge_store.consume(body.mfa_token)
        raise AuthenticationError(LOGIN_FAILED_MESSAGE)

    assert user.id is not None

    verified = await mfa_service.verify_totp(user.id, body.code)
    if not verified:
        verified = await mfa_service.redeem_backup_code(user.id, body.code)
    if not verified:
        await audit_service.log(
            action="auth.login.mfa.verify_failed",
            target=f"user:{user.id}",
            user_id=str(user.id),
            ip_address=ip_address,
            user_agent=request.headers.get("user-agent"),
            tenant_id=challenge["tenant_id"],
        )
        raise AuthenticationError(LOGIN_FAILED_MESSAGE)

    await challenge_store.consume(body.mfa_token)
    result = await authn.complete_authenticated_login(
        user=user,
        tenant_id=challenge["tenant_id"],
        ip_address=ip_address,
        user_agent=request.headers.get("user-agent"),
        audit_action="auth.login.mfa_verified",
    )
    user_response = result.pop("user")
    return ResponseEnvelope(
        data=AuthResponse(**result, user=user_response),
        message="MFA verified",
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
    """Introspect a token â€” return its claims if active."""
    result = await token_svc.introspect(body.refresh_token)
    return ResponseEnvelope(data=result)
