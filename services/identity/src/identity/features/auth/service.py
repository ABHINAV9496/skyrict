"""Authentication feature services — login/register and the token lifecycle.

``AuthenticationService`` authenticates users and issues tokens;
``TokenService`` owns the JWT lifecycle (create, refresh, revoke, introspect).
Both live in this feature because they model the same domain.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from identity.core.config import settings
from identity.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_jwt,
    verify_password,
)
from identity.core.tenant_context import TenantContext
from identity.domain.value_objects import TokenPair
from identity.models.user import UserModel
from skyrict_common.exceptions import (
    InvalidPasswordError,
    TokenExpiredError,
    TokenInvalidError,
    UserAlreadyExistsError,
    UserDisabledError,
    UserNotFoundError,
)

if TYPE_CHECKING:
    from identity.features.audit.service import AuditService
    from identity.features.auth.schemas import LoginRequest, RegisterRequest
    from identity.features.organizations.repository import TenantRepository
    from identity.features.sessions.repository import SessionRepository
    from identity.features.users.repository import UserRepository


class AuthenticationService:
    """Handles user authentication — login, register, password verification."""

    def __init__(
        self,
        user_repo: UserRepository,
        tenant_repo: TenantRepository,
        token_service: TokenService,
        audit_service: AuditService,
    ) -> None:
        self.user_repo = user_repo
        self.tenant_repo = tenant_repo
        self.token_service = token_service
        self.audit_service = audit_service

    async def login(
        self, request: LoginRequest, *, ip_address: str | None = None, user_agent: str | None = None
    ) -> dict[str, Any]:
        """Authenticate a user and return token pair.

        Raises:
            UserNotFoundError: If no user with this email exists.
            InvalidPasswordError: If the password is wrong.
            UserDisabledError: If the user account is disabled.
        """
        # The tenant is resolved ONCE by the middleware (Host subdomain in
        # production, X-Tenant-Slug in dev) and consumed from TenantContext —
        # tokens are bound to the routed tenant so the JWT-vs-routed
        # cross-check passes on every subsequent request.
        tenant_id = TenantContext.get()

        # Emails are unique per tenant, so lookups are tenant-scoped.
        user = await self.user_repo.get_by_email(tenant_id, request.email)
        if not user:
            raise UserNotFoundError()

        if not user.is_active:
            raise UserDisabledError()

        if not verify_password(request.password, user.password_hash):
            raise InvalidPasswordError()

        tokens = await self.token_service.create_token_pair(
            user_id=str(user.id),
            tenant_id=tenant_id,
        )

        await self.audit_service.log(
            action="auth.login.success",
            target=f"user:{user.id}",
            user_id=str(user.id),
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": tokens.token_type,
            "expires_in": tokens.expires_in,
            "user": user,
        }

    async def register(
        self,
        request: RegisterRequest,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        """Register a new user.

        Raises:
            UserAlreadyExistsError: If the email is already taken.
        """
        tenant_id = TenantContext.get()

        if await self.user_repo.email_exists(tenant_id, request.email):
            raise UserAlreadyExistsError()

        hashed = hash_password(request.password)

        user_model = await self.user_repo.create(
            UserModel(
                tenant_id=tenant_id,
                email=request.email,
                password_hash=hashed,
                full_name=request.full_name,
                is_active=True,
                is_verified=False,
            )
        )

        tokens = await self.token_service.create_token_pair(
            user_id=str(user_model.id),
            tenant_id=tenant_id,
        )

        await self.audit_service.log(
            action="auth.register.success",
            target=f"user:{user_model.id}",
            user_id=str(user_model.id),
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": tokens.token_type,
            "expires_in": tokens.expires_in,
            "user": user_model,
        }


class TokenService:
    """Manages JWT token lifecycle — creation, refresh, revocation."""

    def __init__(self, session_repo: SessionRepository) -> None:
        self.session_repo = session_repo

    async def create_token_pair(self, *, user_id: str, tenant_id: str) -> TokenPair:
        """Create an access + refresh token pair."""
        access_token = create_access_token(user_id, tenant_id=tenant_id)
        refresh_token = create_refresh_token(user_id, tenant_id=tenant_id)

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def refresh_tokens(self, refresh_token: str) -> TokenPair:
        """Validate a refresh token and issue a new pair.

        Raises:
            TokenInvalidError: If the refresh token is invalid.
            TokenExpiredError: If the refresh token has expired.
        """
        payload = verify_jwt(refresh_token)

        if payload.get("type") != "refresh":
            raise TokenInvalidError("Token is not a refresh token")

        user_id = payload["sub"]
        tenant_id = payload["tenant_id"]

        # Verify the session is still active
        sessions = await self.session_repo.get_active_by_user(uuid.UUID(user_id))
        if not sessions:
            raise TokenInvalidError("No active session found")

        # Create new pair
        return await self.create_token_pair(user_id=user_id, tenant_id=tenant_id)

    async def revoke_token(self, refresh_token: str) -> None:
        """Revoke a refresh token (invalidate the session)."""
        payload = verify_jwt(refresh_token)
        if payload.get("type") != "refresh":
            raise TokenInvalidError("Token is not a refresh token")

        await self.session_repo.revoke_all_for_user(uuid.UUID(payload["sub"]))

    async def introspect(self, token: str) -> dict[str, Any]:
        """Introspect a token — return its claims if valid."""
        try:
            payload = verify_jwt(token)
            return {
                "active": True,
                "sub": payload.get("sub"),
                "tenant_id": payload.get("tenant_id"),
                "type": payload.get("type"),
                "exp": payload.get("exp"),
            }
        except (TokenExpiredError, TokenInvalidError):
            return {"active": False}
