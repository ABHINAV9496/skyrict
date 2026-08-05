from __future__ import annotations

import hmac
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from identity.core.config import Environment, settings
from identity.core.constants import (
    LOGIN_FAILED_MESSAGE,
    RESERVED_EMAILS,
    RESERVED_SLUGS,
    SYSTEM_ROLE_DEFINITIONS,
)
from identity.core.email import EmailService
from identity.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    mfa_is_required,
    validate_password_policy,
    verify_jwt,
    verify_password,
)
from identity.core.tenant_context import TenantContext
from identity.core.turnstile import TurnstileVerifier
from identity.domain.entities import Role, Tenant, User
from identity.domain.value_objects import TokenPair
from identity.features.auth.mfa_challenge_store import MfaChallengeStore
from identity.features.auth.verification_store import (
    VerificationStore,
    generate_otp,
    generate_verification_token,
    hash_otp,
)
from skyrict_common.exceptions import (
    AuthenticationError,
    ConflictError,
    TokenExpiredError,
    TokenInvalidError,
    TokenReuseDetectedError,
    UserAlreadyExistsError,
    ValidationError,
)

if TYPE_CHECKING:
    from identity.features.audit.service import AuditService
    from identity.features.auth.schemas import (
        CreateOrganizationRequest,
        LoginRequest,
    )
    from identity.features.organizations.ports import TenantRepositoryPort
    from identity.features.roles.ports import RoleRepositoryPort
    from identity.features.sessions.ports import SessionRepositoryPort
    from identity.features.sessions.service import SessionService
    from identity.features.users.ports import UserRepositoryPort

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


_DUMMY_PASSWORD_HASH = hash_password("anti-enumeration-timing-dummy")


def _validate_wizard_password(password: str) -> None:
    validate_password_policy(password)


def _normalize_slug(slug: str) -> str | None:
    normalized = slug.strip().lower()
    if not _SLUG_RE.fullmatch(normalized):
        return None
    return normalized


def _compare_otp(provided: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(provided), expected_hash)


class AuthenticationService:
    def __init__(
        self,
        user_repo: UserRepositoryPort,
        tenant_repo: TenantRepositoryPort,
        role_repo: RoleRepositoryPort,
        token_service: TokenService,
        audit_service: AuditService,
        email_service: EmailService,
        session_service: SessionService,
        verification_store: VerificationStore | None = None,
        turnstile: TurnstileVerifier | None = None,
        mfa_challenge_store: MfaChallengeStore | None = None,
    ) -> None:
        self.user_repo = user_repo
        self.tenant_repo = tenant_repo
        self.role_repo = role_repo
        self.token_service = token_service
        self.audit_service = audit_service
        self.email_service = email_service
        self.session_service = session_service
        self.verification_store = verification_store or VerificationStore()
        self.turnstile = turnstile or TurnstileVerifier()
        self.mfa_challenge_store = mfa_challenge_store or MfaChallengeStore()

    async def login(
        self, request: LoginRequest, *, ip_address: str | None = None, user_agent: str | None = None
    ) -> dict[str, Any]:

        tenant_id = TenantContext.get()

        user = await self.user_repo.get_by_email(tenant_id, request.email)
        if not user:
            verify_password(request.password, _DUMMY_PASSWORD_HASH)
            await self._log_login_failure(
                email=request.email,
                user_id=None,
                ip_address=ip_address,
                user_agent=user_agent,
                tenant_id=tenant_id,
            )
            raise AuthenticationError(LOGIN_FAILED_MESSAGE)

        if not verify_password(request.password, user.password_hash):
            await self._log_login_failure(
                email=request.email,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                tenant_id=tenant_id,
            )
            raise AuthenticationError(LOGIN_FAILED_MESSAGE)

        if not user.is_active:
            await self._log_login_failure(
                email=request.email,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                tenant_id=tenant_id,
            )
            raise AuthenticationError(LOGIN_FAILED_MESSAGE)

        if not user.is_verified:
            await self._log_login_failure(
                email=request.email,
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                tenant_id=tenant_id,
            )
            raise AuthenticationError(LOGIN_FAILED_MESSAGE)

        assert user.id is not None

        if user.mfa_enabled:
            mfa_token = await self.mfa_challenge_store.create(
                user_id=str(user.id),
                tenant_id=tenant_id,
            )
            await self.audit_service.log(
                action="auth.login.mfa_challenged",
                target=f"user:{user.id}",
                user_id=str(user.id),
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return {
                "access_token": None,
                "refresh_token": None,
                "token_type": "Bearer",
                "expires_in": 0,
                "mfa_required": True,
                "mfa_token": mfa_token,
                "next_step": "mfa.verify",
                "user": user,
            }

        roles = await self.role_repo.get_roles_for_user(user.id, tenant_id)
        tenant = await self.tenant_repo.get_by_id(tenant_id)
        mfa_required = mfa_is_required(
            roles=roles,
            mfa_enabled=False,
            tenant_requires_all_members=(
                tenant.mfa_required_for_all_members if tenant is not None else False
            ),
        )

        result = await self.complete_authenticated_login(
            user=user,
            tenant_id=tenant_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        result["mfa_required"] = mfa_required
        result["next_step"] = "mfa.setup" if mfa_required else None
        return result

    async def complete_authenticated_login(
        self,
        *,
        user: User,
        tenant_id: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        audit_action: str = "auth.login.success",
    ) -> dict[str, Any]:

        assert user.id is not None

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
            action=audit_action,
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
            "mfa_required": False,
            "next_step": None,
            "user": user,
        }

    async def _log_login_failure(
        self,
        *,
        email: str,
        user_id: str | uuid.UUID | None,
        ip_address: str | None,
        user_agent: str | None,
        tenant_id: str,
    ) -> None:

        await self.audit_service.log(
            action="auth.login.failed",
            target=f"user:{user_id}" if user_id is not None else f"email:{email}",
            user_id=str(user_id) if user_id is not None else None,
            ip_address=ip_address,
            user_agent=user_agent,
            tenant_id=tenant_id,
        )

    async def signup_start(self, *, email: str, turnstile_token: str | None) -> dict[str, Any]:
        ok = await self.turnstile.verify(turnstile_token)
        if not ok:
            raise ValidationError("Unable to verify you are not a robot. Try again.")
        return {"status": "ok"}

    async def signup_send_code(self, *, email: str) -> dict[str, Any]:
        if await self.verification_store.is_resend_blocked(email):
            return {
                "status": "ok",
                "resend_in": await self.verification_store.resend_in(email),
                "code": None,
            }
        code = generate_otp()
        await self.verification_store.set_otp(email, hash_otp(code))
        await self.verification_store.mark_resend(email)
        await self.email_service.send_otp(to=email, code=code)
        return {
            "status": "ok",
            "resend_in": settings.OTP_RESEND_COOLDOWN_SECONDS,
            "code": code if settings.ENVIRONMENT != Environment.PRODUCTION else None,
        }

    async def signup_verify_code(self, *, email: str, code: str) -> dict[str, Any]:
        if await self.verification_store.get_attempts(email) >= settings.OTP_MAX_ATTEMPTS:
            await self.verification_store.delete_otp(email)
            return {"status": "invalid", "verification_token": None}
        stored_hash = await self.verification_store.get_otp_hash(email)
        if stored_hash is None:
            return {"status": "invalid", "verification_token": None}
        if not _compare_otp(code, stored_hash):
            await self.verification_store.increment_attempts(email)
            return {"status": "invalid", "verification_token": None}
        await self.verification_store.delete_otp(email)
        token = generate_verification_token()
        await self.verification_store.set_verification_token(token, email, "")
        return {"status": "ok", "verification_token": token}

    async def signup_set_password(
        self, *, email: str, verification_token: str, password: str
    ) -> dict[str, Any]:
        _validate_wizard_password(password)
        await self._require_verification_token(verification_token, email)
        await self.verification_store.update_verification_token_password(
            verification_token, hash_password(password)
        )
        return {"status": "ok"}

    async def signup_check_email(self, *, email: str) -> dict[str, Any]:
        normalized = email.lower().strip()
        available = not await self.user_repo.email_exists_global(normalized)
        available = available and normalized not in RESERVED_EMAILS
        return {"available": available}

    async def signup_check_slug(self, *, slug: str) -> dict[str, Any]:
        normalized = _normalize_slug(slug)
        if normalized is None or normalized in RESERVED_SLUGS:
            return {"available": False}
        if await self.tenant_repo.slug_exists(normalized):
            return {"available": False}
        return {"available": True}

    async def signup_create_organization(
        self, request: CreateOrganizationRequest, *, ip_address: str | None, user_agent: str | None
    ) -> dict[str, Any]:
        payload = await self._require_verification_token(request.verification_token, request.email)
        if not payload["password_hash"]:
            raise TokenInvalidError("Password has not been set for this session")
        slug = _normalize_slug(request.workspace_slug)
        if slug is None:
            raise ValidationError(
                "Workspace slug may only contain lowercase letters, numbers, and hyphens"
            )
        if slug in RESERVED_SLUGS or await self.tenant_repo.slug_exists(slug):
            raise ConflictError("This workspace URL is already taken")
        if await self.user_repo.email_exists_global(request.email):
            raise UserAlreadyExistsError()

        tenant_id = uuid.uuid4()
        await self.tenant_repo.create(
            Tenant(
                name=request.company_name,
                slug=slug,
                plan_tier=request.plan_id,
                industry=request.industry,
                billing_address=self._billing_address_payload(request),
                id=tenant_id,
            )
        )

        roles = await self._create_system_roles(tenant_id)
        owner_role = roles["tenant_owner"]

        user = await self.user_repo.create(
            User(
                tenant_id=tenant_id,
                email=request.email,
                password_hash=payload["password_hash"],
                full_name=request.owner_full_name,
                is_active=True,
                is_verified=True,
                phone_country=request.phone_country,
                phone_number=request.phone_number,
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

        await self.audit_service.log(
            action="auth.register.success",
            target=f"user:{user.id}",
            user_id=str(user.id),
            ip_address=ip_address,
            user_agent=user_agent,
            tenant_id=str(tenant_id),
        )

        await self.verification_store.delete_verification_token(request.verification_token)

        return {
            "status": "ok",
            "mfa_required": True,
            "tenant_id": tenant_id,
            "tenant_slug": slug,
        }

    async def _require_verification_token(self, token: str, email: str) -> dict[str, str]:
        payload = await self.verification_store.get_verification_token(token)
        if payload is None or payload["email"].lower() != email.lower():
            raise TokenInvalidError("Verification session is invalid or expired")
        return payload

    @staticmethod
    def _billing_address_payload(request: CreateOrganizationRequest) -> dict[str, Any] | None:
        if request.address is None:
            return None
        address = request.address
        return {
            "country": address.country,
            "addressLine1": address.address_line1,
            "addressLine2": address.address_line2,
            "city": address.city,
            "state": address.state,
            "postalCode": address.postal_code,
        }

    async def _create_system_roles(self, tenant_id: uuid.UUID) -> dict[str, Role]:
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

        access_token = create_access_token(user_id, tenant_id=tenant_id)
        refresh_token = create_refresh_token(user_id, tenant_id=tenant_id, session_id=session_id)

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def refresh_tokens(self, refresh_token: str) -> TokenPair:
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
