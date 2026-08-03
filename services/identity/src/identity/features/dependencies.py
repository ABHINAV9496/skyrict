"""FastAPI dependency injection — get_db, get_current_user, require_permission.

Every route that touches the database or requires auth goes through these deps.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from identity.api.middleware import cross_check_jwt_tenant
from identity.core.security import verify_jwt
from identity.core.tenant_context import TenantContext
from identity.db.session import async_session_factory
from identity.features.audit.repository import AuditRepository
from identity.features.audit.service import AuditService
from identity.features.auth.service import AuthenticationService, TokenService
from identity.features.mfa.service import MFAService
from identity.features.organizations.repository import TenantRepository
from identity.features.passkeys.service import PasskeyService
from identity.features.roles.service import AuthorizationService
from identity.features.sessions.repository import SessionRepository
from identity.features.sessions.service import SessionService
from identity.features.sso.service import SSOService
from identity.features.users.repository import UserRepository
from skyrict_common.exceptions import AuthenticationError

security = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session; commit on success, roll back on error.

    Without the commit, every write made by a route handler (user registration,
    audit logs, session revocation) is rolled back when the session closes —
    registration was returning tokens for a user that never persisted.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        finally:
            await session.close()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Extract and verify JWT from Authorization header, return user claims.

    Uses security.verify_jwt() — the ONE AND ONLY decode path.
    The tenant is consumed from TenantContext (resolved once by the middleware)
    and the JWT-vs-routed cross-check is enforced again here as defense in
    depth, so a token can never be used against a different tenant even if a
    route is reached without going through the middleware.

    Raises:
        AuthenticationError: If no token, token is invalid, or token is expired.
        TenantContextMissingError: If the middleware hasn't resolved a tenant.
        TenantMismatchError: If the token's tenant claim differs from the routed tenant.
    """
    if credentials is None:
        raise AuthenticationError("Missing Authorization header")

    payload = verify_jwt(credentials.credentials)

    if payload.get("type") != "access":
        raise AuthenticationError("Invalid token type")

    # Single source of truth: the routed tenant was resolved by the middleware.
    routed_tenant_id = TenantContext.get()
    cross_check_jwt_tenant(payload.get("tenant_id"), routed_tenant_id)
    TenantContext.set_user_id(payload["sub"])

    return {
        "user_id": payload["sub"],
        "tenant_id": routed_tenant_id,
        "token_payload": payload,
    }


def require_permission(permission: str) -> Callable[[], Awaitable[dict[str, Any]]]:
    """Dependency factory — returns a dependency that checks a specific permission."""

    async def _check(
        current_user: dict[str, Any] = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> dict[str, Any]:
        authz = AuthorizationService(UserRepository(db))
        await authz.require_permission(
            user_id=current_user["user_id"],
            permission=permission,
            tenant_id=current_user["tenant_id"],
        )
        return current_user

    return _check


# --- Repository/Service deps ---


def get_user_repo(db: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_tenant_repo(db: AsyncSession = Depends(get_db)) -> TenantRepository:
    return TenantRepository(db)


def get_session_repo(db: AsyncSession = Depends(get_db)) -> SessionRepository:
    return SessionRepository(db)


def get_audit_repo(db: AsyncSession = Depends(get_db)) -> AuditRepository:
    return AuditRepository(db)


def get_token_service(session_repo: SessionRepository = Depends(get_session_repo)) -> TokenService:
    return TokenService(session_repo)


def get_audit_service(audit_repo: AuditRepository = Depends(get_audit_repo)) -> AuditService:
    return AuditService(audit_repo)


def get_authn_service(
    user_repo: UserRepository = Depends(get_user_repo),
    tenant_repo: TenantRepository = Depends(get_tenant_repo),
    token_service: TokenService = Depends(get_token_service),
    audit_service: AuditService = Depends(get_audit_service),
) -> AuthenticationService:
    return AuthenticationService(user_repo, tenant_repo, token_service, audit_service)


def get_mfa_service(user_repo: UserRepository = Depends(get_user_repo)) -> MFAService:
    return MFAService(user_repo)


def get_session_service(
    session_repo: SessionRepository = Depends(get_session_repo),
) -> SessionService:
    return SessionService(session_repo)


def get_passkey_service(user_repo: UserRepository = Depends(get_user_repo)) -> PasskeyService:
    return PasskeyService(user_repo)


def get_sso_service(user_repo: UserRepository = Depends(get_user_repo)) -> SSOService:
    return SSOService(user_repo)
