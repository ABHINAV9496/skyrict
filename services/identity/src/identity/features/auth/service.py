"""Authentication feature services — login/register and the token lifecycle.

``AuthenticationService`` authenticates users, self-service provisions new
tenants, and verifies emails; ``TokenService`` owns the JWT lifecycle (create,
refresh, revoke, introspect). Both live in this feature because they model the
same domain.

The tenant is resolved ONCE by the middleware (Host subdomain in production,
X-Tenant-Slug in dev) and consumed from TenantContext — except self-service
registration, which runs without a routed tenant (the request bypasses tenant
resolution via SKIP_AUTH_PATHS) and provisions its own.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from identity.core.config import Environment, settings
from identity.core.constants import SYSTEM_ROLE_DEFINITIONS
from identity.core.email import EmailService
from identity.core.security import (
    create_access_token,
    create_email_verification_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_jwt,
    verify_password,
)
from identity.core.tenant_context import TenantContext
from identity.domain.entities import Role, Tenant, User
from identity.domain.value_objects import TokenPair
from skyrict_common.exceptions import (
    EmailNotVerifiedError,
    InvalidPasswordError,
    TokenExpiredError,
    TokenInvalidError,
    TokenReuseDetectedError,
    UserDisabledError,
    UserNotFoundError,
)

if TYPE_CHECKING:
    from identity.features.audit.service import AuditService
    from identity.features.auth.schemas import LoginRequest, RegisterRequest
    from identity.features.organizations.ports import TenantRepositoryPort
    from identity.features.roles.ports import RoleRepositoryPort
    from identity.features.sessions.ports import SessionRepositoryPort
    from identity.features.sessions.service import SessionService
    from identity.features.users.ports import UserRepositoryPort

_SLUG_SEPARATOR_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """Lowercase, hyphen-separated slug from a display name."""
    slug = _SLUG_SEPARATOR_RE.sub("-", name.lower()).strip("-")
    return slug[:100] or "organization"


class AuthenticationService:
    """Handles user authentication, provisioning, and email verification."""

    def __init__(
        self,
        user_repo: UserRepositoryPort,
        tenant_repo: TenantRepositoryPort,
        role_repo: RoleRepositoryPort,
        token_service: TokenService,
        audit_service: AuditService,
        email_service: EmailService,
        session_service: SessionService,
    ) -> None:
        self.user_repo = user_repo
        self.tenant_repo = tenant_repo
        self.role_repo = role_repo
        self.token_service = token_service
        self.audit_service = audit_service
        self.email_service = email_service
        self.session_service = session_service

    async def login(
        self, request: LoginRequest, *, ip_address: str | None = None, user_agent: str | None = None
    ) -> dict[str, Any]:
        """Authenticate a user and return a token pair (plus MFA posture).

        Raises:
            UserNotFoundError: If no user with this email exists.
            EmailNotVerifiedError: If the account has not verified its email.
            UserDisabledError: If the user account is disabled.
            InvalidPasswordError: If the password is wrong.
        """
        tenant_id = TenantContext.get()

        # Emails are unique per tenant, so lookups are tenant-scoped.
        user = await self.user_repo.get_by_email(tenant_id, request.email)
        if not user:
            raise UserNotFoundError()

        if not user.is_active:
            raise UserDisabledError()

        # Verification gate: unverified accounts cannot sign in.
        if not user.is_verified:
            raise EmailNotVerifiedError()

        if not verify_password(request.password, user.password_hash):
            raise InvalidPasswordError()

        assert user.id is not None

        # Forced MFA: tenant owners must complete MFA setup before the flag clears.
        roles = await self.role_repo.get_roles_for_user(user.id, tenant_id)
        mfa_required = "tenant_owner" in roles and not user.mfa_enabled

        session_id = uuid.uuid4()
        tokens = await self.token_service.create_token_pair(
            user_id=str(user.id),
            tenant_id=tenant_id,
            session_id=str(session_id),
        )

        new_device = not await self.session_service.has_prior_device(
            user.id,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        await self.session_service.create_session(
            session_id=session_id,
            user_id=user.id,
            tenant_id=uuid.UUID(tenant_id),
            refresh_token_hash=hash_refresh_token(tokens.refresh_token),
            user_agent=user_agent,
            ip_address=ip_address,
        )

        await self.audit_service.log(
            action="auth.login.success",
            target=f"user:{user.id}",
            user_id=str(user.id),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        if new_device:
            await self.email_service.send_security_alert(
                to=user.email,
                full_name=user.full_name,
                event_type="new_device",
                ip_address=ip_address,
                user_agent=user_agent,
            )

        return {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": tokens.token_type,
            "expires_in": tokens.expires_in,
            "mfa_required": mfa_required,
            "user": user,
        }

    async def register(
        self,
        request: RegisterRequest,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        """Self-service provisioning: tenant, system roles, owner, and grant.

        All writes happen on the caller's request session and are committed
        together, so a failure anywhere rolls back the whole provisioning (no
        orphan tenants/roles/users). Returns a verification-pending response —
        no tokens are issued; login stays blocked until the email is verified.

        Never raises on a taken email (anti-enumeration): the response is the
        same shape regardless.
        """
        slug = await self._allocate_slug(request.organization_name)
        tenant_id = uuid.uuid4()

        await self.tenant_repo.create(
            Tenant(name=request.organization_name, slug=slug, id=tenant_id)
        )

        roles = await self._create_system_roles(tenant_id)
        owner_role = roles["tenant_owner"]

        user = await self.user_repo.create(
            User(
                tenant_id=tenant_id,
                email=request.email,
                password_hash=hash_password(request.password),
                full_name=request.full_name,
                is_active=True,
                is_verified=False,
            )
        )

        assert user.id is not None
        assert owner_role.id is not None

        await self.role_repo.grant_to_user(
            user_id=user.id,
            role_id=owner_role.id,
            tenant_id=tenant_id,
            scope_id=tenant_id,
        )

        verification_token = create_email_verification_token(str(user.id), tenant_id=str(tenant_id))

        await self.audit_service.log(
            action="auth.register.success",
            target=f"user:{user.id}",
            user_id=str(user.id),
            ip_address=ip_address,
            user_agent=user_agent,
            tenant_id=str(tenant_id),
        )
        await self.email_service.send_verification(
            to=request.email,
            full_name=request.full_name,
            token=verification_token,
            base_url=settings.EMAIL_VERIFICATION_BASE_URL or None,
        )

        # Verification tokens are exposed only outside production (dev/test).
        return {
            "email": request.email,
            "user_id": user.id,
            "tenant_id": tenant_id,
            "tenant_slug": slug,
            "verification_pending": True,
            "verification_token": (
                verification_token if settings.ENVIRONMENT != Environment.PRODUCTION else None
            ),
            "expires_in": settings.VERIFICATION_TOKEN_EXPIRE_MINUTES * 60,
        }

    async def verify_email(self, token: str) -> None:
        """Mark the account verified when the token is valid (idempotent).

        Raises:
            TokenInvalidError: If the token is malformed, wrong purpose, or
                its tenant does not match the user.
            UserNotFoundError: If the token's subject no longer exists.
        """
        payload = verify_jwt(token)
        if payload.get("type") != "email_verify":
            raise TokenInvalidError("Token is not an email verification token")

        user = await self.user_repo.get_by_id(uuid.UUID(payload["sub"]))
        if user is None:
            raise UserNotFoundError()

        token_tenant = payload.get("tenant_id")
        if token_tenant is not None and str(token_tenant) != str(user.tenant_id):
            raise TokenInvalidError("Verification token tenant does not match the user")

        if not user.is_verified:
            assert user.id is not None
            await self.user_repo.mark_verified(user.id)

    async def _allocate_slug(self, organization_name: str) -> str:
        """Return a collision-safe slug: base name, suffixed on clash."""
        base = _slugify(organization_name)
        candidate = base
        suffix = 2
        while await self.tenant_repo.slug_exists(candidate):
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    async def _create_system_roles(self, tenant_id: uuid.UUID) -> dict[str, Role]:
        """Provision the platform-defined system roles for a tenant."""
        roles: dict[str, Role] = {}
        for name, permissions in SYSTEM_ROLE_DEFINITIONS:
            role = await self.role_repo.create(
                Role(
                    tenant_id=tenant_id,
                    name=name,
                    permissions=list(permissions),
                    is_system_role=True,
                )
            )
            roles[name] = role
        return roles


class TokenService:
    """Manages JWT token lifecycle — creation, refresh, revocation."""

    def __init__(self, session_repo: SessionRepositoryPort, audit_service: AuditService) -> None:
        self.session_repo = session_repo
        self.audit_service = audit_service

    async def create_token_pair(
        self,
        *,
        user_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> TokenPair:
        """Create an access + refresh token pair."""
        access_token = create_access_token(user_id, tenant_id=tenant_id)
        refresh_token = create_refresh_token(user_id, tenant_id=tenant_id, session_id=session_id)

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def refresh_tokens(self, refresh_token: str) -> TokenPair:
        """Validate a refresh token, rotate it, and issue a new pair."""
        payload = verify_jwt(refresh_token)

        if payload.get("type") != "refresh":
            raise TokenInvalidError("Token is not a refresh token")

        user_id = payload["sub"]
        tenant_id = payload["tenant_id"]
        session_id = payload.get("session_id")

        session = await self.session_repo.get_by_id(session_id) if session_id else None
        if (
            session is None
            or session.user_id != uuid.UUID(user_id)
            or not session.is_active
            or session.refresh_token_hash != hash_refresh_token(refresh_token)
        ):
            await self._handle_reuse(user_id=user_id, tenant_id=tenant_id, session_id=session_id)
            raise TokenReuseDetectedError()

        assert session.id is not None
        if session.expires_at <= datetime.now(UTC):
            await self._handle_reuse(user_id=user_id, tenant_id=tenant_id, session_id=session_id)
            raise TokenReuseDetectedError()

        tokens = await self.create_token_pair(
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
        )
        await self.session_repo.rotate(
            session.id,
            refresh_token_hash=hash_refresh_token(tokens.refresh_token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        await self.audit_service.log(
            action="auth.refresh.success",
            target=f"session:{session.id}",
            user_id=user_id,
            tenant_id=tenant_id,
        )
        return tokens

    async def _handle_reuse(self, *, user_id: str, tenant_id: str, session_id: str | None) -> None:
        await self.session_repo.revoke_all_for_user(uuid.UUID(user_id))
        await self.audit_service.log(
            action="auth.refresh.reuse_detected",
            target=f"session:{session_id}",
            user_id=user_id,
            tenant_id=tenant_id,
        )
        await self.session_repo.commit()

    async def revoke_token(self, refresh_token: str) -> None:
        """Revoke a refresh token (invalidate the session)."""
        payload = verify_jwt(refresh_token)
        if payload.get("type") != "refresh":
            raise TokenInvalidError("Token is not a refresh token")

        user_id = payload["sub"]
        session_id = payload.get("session_id")
        session = await self.session_repo.get_by_id(session_id) if session_id else None
        if session is not None and session.user_id == uuid.UUID(user_id):
            assert session.id is not None
            await self.session_repo.revoke_session(session.id)

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
