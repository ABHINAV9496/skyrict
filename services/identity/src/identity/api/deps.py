"""
FastAPI dependency injection â€” get_db, get_current_user, require_permission.

The api layer is the sole composition point: feature services and repositories
are wired together here and nowhere else. Feature imports stay inside the
factory functions (call sites) so importing this module never pulls the whole
feature tree at load time, and no feature ever imports another feature.

Every route that touches the database or requires auth goes through these deps.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from identity.core.email import EmailService, LogEmailService
from identity.core.rate_limit import RateLimiter
from identity.core.rate_limit import limiter as default_rate_limiter
from identity.core.security import verify_jwt
from identity.core.tenant_context import TenantContext
from identity.core.turnstile import TurnstileVerifier
from identity.db.session import async_session_factory
from identity.features.audit.repository import AuditRepository
from identity.features.auth.mfa_challenge_store import MfaChallengeStore
from identity.features.auth.security import cross_check_jwt_tenant
from identity.features.auth.verification_store import VerificationStore
from identity.features.organizations.repository import TenantRepository
from identity.features.roles.repository import RoleRepository
from identity.features.sessions.repository import SessionRepository
from identity.features.users.repository import UserRepository
from skyrict_common.exceptions import AuthenticationError, MFARequiredError

if TYPE_CHECKING:
    from identity.features.audit.service import AuditService
    from identity.features.auth.service import AuthenticationService, TokenService
    from identity.features.invitations.repository import InvitationRepository
    from identity.features.invitations.service import InvitationService
    from identity.features.mfa.service import MFAService
    from identity.features.organizations.service import TenantService
    from identity.features.roles.service import RoleManagementService
    from identity.features.sessions.service import SessionService
    from identity.features.users.service import UserService

security = HTTPBearer(auto_error=False)


_MFA_EXEMPT_PATHS = frozenset({"/api/v1/mfa/setup", "/api/v1/mfa/verify"})


async def _enforce_mfa_enrollment(*, db: AsyncSession, user_id: str, tenant_id: str) -> None:
    """
    Block authenticated calls while forced MFA is not yet set up.

    Raises:
        MFARequiredError: When MFA is mandatory for this account (tenant owner
            or tenant-level policy) but not yet enabled.
    """
    from identity.core.security import mfa_is_required

    user = await UserRepository(db).get_by_id(user_id)
    if user is None:
        return
    roles = await RoleRepository(db).get_roles_for_user(user_id, tenant_id)
    tenant = await TenantRepository(db).get_by_id(tenant_id)
    if mfa_is_required(
        roles=roles,
        mfa_enabled=user.mfa_enabled,
        tenant_requires_all_members=(
            tenant.mfa_required_for_all_members if tenant is not None else False
        ),
    ):
        raise MFARequiredError()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an async database session; commit on success, roll back on error.

    Without the commit, every write made by a route handler (user registration,
    audit logs, session revocation) is rolled back when the session closes â€”
    registration was returning tokens for a user that never persisted.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        finally:
            await session.close()


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Extract and verify JWT from Authorization header, return user claims.

    Uses security.verify_jwt() â€” the ONE AND ONLY decode path.
    The tenant is consumed from TenantContext (resolved once by the middleware)
    and the JWT-vs-routed cross-check is enforced again here as defense in
    depth, so a token can never be used against a different tenant even if a
    route is reached without going through the middleware.

    Enforces the MFA gate on every authenticated route except the enrollment
    endpoints (``/api/v1/mfa/setup``, ``/api/v1/mfa/verify``): accounts that
    must enroll (tenant owner or tenant policy) get 403 MFARequiredError until
    MFA is enabled.

    Raises:
        AuthenticationError: If no token, token is invalid, or token is expired.
        MFARequiredError: If MFA is mandatory for this account but not enabled.
        TenantContextMissingError: If the middleware hasn't resolved a tenant.
        TenantMismatchError: If the token's tenant claim differs from the routed tenant.
    """
    if credentials is None:
        raise AuthenticationError("Missing Authorization header")

    payload = verify_jwt(credentials.credentials)

    if payload.get("type") != "access":
        raise AuthenticationError("Invalid token type")

    routed_tenant_id = TenantContext.get()
    cross_check_jwt_tenant(payload.get("tenant_id"), routed_tenant_id)
    TenantContext.set_user_id(payload["sub"])

    if request.url.path not in _MFA_EXEMPT_PATHS:
        await _enforce_mfa_enrollment(db=db, user_id=payload["sub"], tenant_id=routed_tenant_id)

    return {
        "user_id": payload["sub"],
        "tenant_id": routed_tenant_id,
        "token_payload": payload,
    }


def require_permission(permission: str) -> Callable[[], Awaitable[dict[str, Any]]]:
    """Dependency factory â€” returns a dependency that checks a specific permission."""

    async def _check(
        current_user: dict[str, Any] = Depends(get_current_user),
        user_repo: UserRepository = Depends(get_user_repo),
        role_repo: RoleRepository = Depends(get_role_repo),
    ) -> dict[str, Any]:
        from identity.features.roles.service import AuthorizationService

        user = await user_repo.get_by_id(current_user["user_id"])
        authz = AuthorizationService(role_repo)
        await authz.require_permission(
            user_is_active=user is not None and user.is_active,
            user_id=current_user["user_id"],
            permission=permission,
            tenant_id=current_user["tenant_id"],
        )
        return current_user

    return _check


def get_user_repo(db: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_tenant_repo(db: AsyncSession = Depends(get_db)) -> TenantRepository:
    return TenantRepository(db)


def get_session_repo(db: AsyncSession = Depends(get_db)) -> SessionRepository:
    return SessionRepository(db)


def get_audit_repo(db: AsyncSession = Depends(get_db)) -> AuditRepository:
    return AuditRepository(db)


def get_role_repo(db: AsyncSession = Depends(get_db)) -> RoleRepository:
    return RoleRepository(db)


def get_audit_service(audit_repo: AuditRepository = Depends(get_audit_repo)) -> AuditService:
    from identity.features.audit.service import AuditService

    return AuditService(audit_repo)


def get_token_service(
    session_repo: SessionRepository = Depends(get_session_repo),
    audit_service: AuditService = Depends(get_audit_service),
) -> TokenService:
    from identity.features.auth.service import TokenService

    return TokenService(session_repo, audit_service)


def get_email_service() -> EmailService:
    """Email transport â€” log-based until a real provider is wired."""
    return LogEmailService()


def get_rate_limiter() -> RateLimiter:
    """Return the process-wide rate limiter (Redis-backed, fail-open)."""
    return default_rate_limiter


def get_verification_store() -> VerificationStore:
    """Return the Redis-backed OTP / verification-token store."""
    return VerificationStore()


def get_mfa_challenge_store() -> MfaChallengeStore:
    return MfaChallengeStore()


def get_turnstile_verifier() -> TurnstileVerifier:
    """Return the Cloudflare Turnstile server-side verifier."""
    return TurnstileVerifier()


def get_session_service(
    session_repo: SessionRepository = Depends(get_session_repo),
) -> SessionService:
    from identity.features.sessions.service import SessionService

    return SessionService(session_repo)


def get_authn_service(
    user_repo: UserRepository = Depends(get_user_repo),
    tenant_repo: TenantRepository = Depends(get_tenant_repo),
    role_repo: RoleRepository = Depends(get_role_repo),
    token_service: TokenService = Depends(get_token_service),
    audit_service: AuditService = Depends(get_audit_service),
    email_service: EmailService = Depends(get_email_service),
    session_service: SessionService = Depends(get_session_service),
    verification_store: VerificationStore = Depends(get_verification_store),
    turnstile: TurnstileVerifier = Depends(get_turnstile_verifier),
) -> AuthenticationService:
    from identity.features.auth.service import AuthenticationService

    return AuthenticationService(
        user_repo,
        tenant_repo,
        role_repo,
        token_service,
        audit_service,
        email_service,
        session_service,
        verification_store=verification_store,
        turnstile=turnstile,
    )


def get_roles_service(role_repo: RoleRepository = Depends(get_role_repo)) -> RoleManagementService:
    from identity.features.roles.service import RoleManagementService

    return RoleManagementService(role_repo)


def get_user_service(user_repo: UserRepository = Depends(get_user_repo)) -> UserService:
    from identity.features.users.service import UserService

    return UserService(user_repo)


def get_tenant_service(tenant_repo: TenantRepository = Depends(get_tenant_repo)) -> TenantService:
    from identity.features.organizations.service import TenantService

    return TenantService(tenant_repo)


def get_invitation_repo(
    db: AsyncSession = Depends(get_db),
) -> InvitationRepository:
    from identity.features.invitations.repository import InvitationRepository

    return InvitationRepository(db)


def get_invitation_service(
    invitation_repo: InvitationRepository = Depends(get_invitation_repo),
    user_repo: UserRepository = Depends(get_user_repo),
    role_repo: RoleRepository = Depends(get_role_repo),
    email_service: EmailService = Depends(get_email_service),
) -> InvitationService:
    from identity.features.invitations.service import InvitationService

    return InvitationService(invitation_repo, user_repo, role_repo, email_service)


def get_mfa_service(
    user_repo: UserRepository = Depends(get_user_repo),
    role_repo: RoleRepository = Depends(get_role_repo),
    audit_service: AuditService = Depends(get_audit_service),
) -> MFAService:
    from identity.features.mfa.service import MFAService

    return MFAService(user_repo, role_repo, audit_service)
