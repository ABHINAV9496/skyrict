"""Unit tests for the auth feature AuthenticationService (fake ports)."""

from __future__ import annotations

import uuid

import pytest

from identity.core.config import settings
from identity.core.constants import LOGIN_FAILED_MESSAGE, SYSTEM_ROLE_DEFINITIONS
from identity.core.security import (
    create_access_token,
    create_email_verification_token,
    hash_password,
)
from identity.core.tenant_context import TenantContext
from identity.domain.entities import Role, Session, Tenant, User
from identity.domain.value_objects import TokenPair
from identity.features.auth.schemas import LoginRequest, RegisterRequest
from identity.features.auth.service import AuthenticationService
from skyrict_common.exceptions import AuthenticationError, TokenInvalidError, UserNotFoundError


class FakeUserRepo:
    """In-memory UserRepositoryPort double (subset used by auth flows)."""

    def __init__(self, users: list[User] | None = None) -> None:
        self.users: dict[uuid.UUID, User] = {}
        for user in users or []:
            if user.id is None:
                user.id = uuid.uuid4()
            self.users[user.id] = user
        self.created: list[User] = []

    async def get_by_id(self, user_id: str | uuid.UUID) -> User | None:
        return self.users.get(uuid.UUID(str(user_id)))

    async def get_by_email(self, tenant_id: str | uuid.UUID, email: str) -> User | None:
        for user in self.users.values():
            if user.email == email and str(user.tenant_id) == str(tenant_id):
                return user
        return None

    async def email_exists(self, tenant_id: str | uuid.UUID, email: str) -> bool:
        return await self.get_by_email(tenant_id, email) is not None

    async def create(self, user: User) -> User:
        if user.id is None:
            user.id = uuid.uuid4()
        self.users[user.id] = user
        self.created.append(user)
        return user

    async def update_profile(
        self,
        user_id: str | uuid.UUID,
        *,
        full_name: str | None = None,
        email: str | None = None,
    ) -> User:
        user = await self.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        if full_name is not None:
            user.full_name = full_name
        if email is not None:
            user.email = email
        return user

    async def update_password_hash(self, user_id: str | uuid.UUID, password_hash: str) -> User:
        user = await self.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        user.password_hash = password_hash
        return user

    async def mark_verified(self, user_id: str | uuid.UUID) -> User:
        user = await self.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        user.is_verified = True
        return user


class FakeTenantRepo:
    """In-memory TenantRepositoryPort double."""

    def __init__(self, tenants: list[Tenant] | None = None) -> None:
        self.tenants: dict[uuid.UUID, Tenant] = {}
        for tenant in tenants or []:
            if tenant.id is None:
                tenant.id = uuid.uuid4()
            self.tenants[tenant.id] = tenant
        self.created: list[Tenant] = []

    async def get_by_id(self, tenant_id: str | uuid.UUID) -> Tenant | None:
        return self.tenants.get(uuid.UUID(str(tenant_id)))

    async def get_by_slug(self, slug: str) -> Tenant | None:
        for tenant in self.tenants.values():
            if tenant.slug == slug:
                return tenant
        return None

    async def slug_exists(self, slug: str) -> bool:
        return await self.get_by_slug(slug) is not None

    async def create(self, tenant: Tenant) -> Tenant:
        if tenant.id is None:
            tenant.id = uuid.uuid4()
        self.tenants[tenant.id] = tenant
        self.created.append(tenant)
        return tenant


class FakeRoleRepo:
    """In-memory RoleRepositoryPort double."""

    def __init__(self, roles_for_user: dict[uuid.UUID, list[str]] | None = None) -> None:
        self.roles_by_user: dict[uuid.UUID, list[str]] = dict(roles_for_user or {})
        self.created: list[Role] = []
        self.grants: list[tuple[str, str, str, str]] = []

    async def create(self, role: Role) -> Role:
        if role.id is None:
            role.id = uuid.uuid4()
        self.created.append(role)
        return role

    async def get_by_id(self, role_id: str | uuid.UUID) -> Role | None:
        for role in self.created:
            if role.id is not None and str(role.id) == str(role_id):
                return role
        return None

    async def get_by_name(self, tenant_id: str | uuid.UUID, name: str) -> Role | None:
        for role in self.created:
            if role.name == name and str(role.tenant_id) == str(tenant_id):
                return role
        return None

    async def list_by_tenant(
        self, tenant_id: str | uuid.UUID, *, offset: int = 0, limit: int = 20
    ) -> list[Role]:
        roles = [role for role in self.created if str(role.tenant_id) == str(tenant_id)]
        return roles[offset : offset + limit]

    async def grant_to_user(
        self,
        *,
        user_id: str | uuid.UUID,
        role_id: str | uuid.UUID,
        tenant_id: str | uuid.UUID,
        scope_id: str | uuid.UUID,
        scope_type=...,
    ) -> None:
        self.grants.append((str(user_id), str(role_id), str(tenant_id), str(scope_id)))

    async def get_roles_for_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID
    ) -> list[str]:
        return self.roles_by_user.get(uuid.UUID(str(user_id)), [])


class FakeTokenService:
    """TokenService double — returns a fixed TokenPair, records call args."""

    def __init__(self) -> None:
        self.pairs_created: list[tuple[str, str, str | None]] = []

    async def create_token_pair(
        self, *, user_id: str, tenant_id: str, session_id: str | None = None
    ) -> TokenPair:
        self.pairs_created.append((user_id, tenant_id, session_id))
        return TokenPair(access_token="access-token", refresh_token="refresh-token")


class FakeAuditService:
    """AuditService double — records log() calls."""

    def __init__(self) -> None:
        self.events: list[dict[str, str | None]] = []

    async def log(
        self,
        *,
        action: str,
        target: str,
        user_id: str | None = None,
        details: dict[str, object] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self.events.append(
            {"action": action, "target": target, "user_id": user_id, "tenant_id": tenant_id}
        )


class FakeEmailService:
    """EmailService double — records send_verification calls."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str | None]] = []

    async def send_verification(
        self, *, to: str, full_name: str, token: str, base_url: str | None = None
    ) -> None:
        self.sent.append({"to": to, "full_name": full_name, "token": token, "base_url": base_url})

    async def send_security_alert(
        self,
        *,
        to: str,
        full_name: str,
        event_type: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.sent.append(
            {
                "to": to,
                "full_name": full_name,
                "event_type": event_type,
                "ip_address": ip_address,
                "user_agent": user_agent,
            }
        )


class FakeSessionService:
    def __init__(self, prior_device: bool = True) -> None:
        self.prior_device = prior_device
        self.created: list[Session] = []
        self.prior_device_checks: list[tuple[uuid.UUID, str | None, str | None]] = []

    async def has_prior_device(
        self,
        user_id: str | uuid.UUID,
        *,
        user_agent: str | None,
        ip_address: str | None,
    ) -> bool:
        self.prior_device_checks.append((uuid.UUID(str(user_id)), user_agent, ip_address))
        return self.prior_device

    async def create_session(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        refresh_token_hash: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
        device_info: dict[str, object] | None = None,
        location: str | None = None,
        session_id: uuid.UUID | None = None,
    ) -> Session:
        session = Session(
            id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            refresh_token_hash=refresh_token_hash,
            user_agent=user_agent,
            ip_address=ip_address,
            device_info=device_info,
            location=location,
        )
        self.created.append(session)
        return session


class _Harness:
    """Wires AuthenticationService against in-memory port doubles."""

    def __init__(
        self,
        *,
        users: list[User] | None = None,
        tenants: list[Tenant] | None = None,
        roles_for_user: dict[uuid.UUID, list[str]] | None = None,
        prior_device: bool = True,
    ) -> None:
        self.user_repo = FakeUserRepo(users)
        self.tenant_repo = FakeTenantRepo(tenants)
        self.role_repo = FakeRoleRepo(roles_for_user)
        self.token_svc = FakeTokenService()
        self.audit_svc = FakeAuditService()
        self.email_svc = FakeEmailService()
        self.session_svc = FakeSessionService(prior_device=prior_device)
        self.service = AuthenticationService(
            self.user_repo,
            self.tenant_repo,
            self.role_repo,
            self.token_svc,
            self.audit_svc,
            self.email_svc,
            self.session_svc,
        )


@pytest.fixture
def tenant_ctx() -> str:
    tenant_id = str(uuid.uuid4())
    TenantContext.set(tenant_id)
    yield tenant_id
    TenantContext.reset()


def _make_user(
    *,
    tenant_id: uuid.UUID | None = None,
    email: str = "user@example.com",
    password: str = "Password1!",
    is_active: bool = True,
    is_verified: bool = True,
    mfa_enabled: bool = False,
) -> User:
    return User(
        tenant_id=tenant_id if tenant_id is not None else uuid.UUID(TenantContext.get()),
        email=email,
        password_hash=hash_password(password),
        full_name="Test User",
        is_active=is_active,
        is_verified=is_verified,
        mfa_enabled=mfa_enabled,
        id=uuid.uuid4(),
    )


class TestLogin:
    async def test_success_returns_tokens_and_user(self, tenant_ctx: str) -> None:
        user = _make_user()
        harness = _Harness(users=[user])

        result = await harness.service.login(LoginRequest(email=user.email, password="Password1!"))

        assert result["access_token"] == "access-token"
        assert result["refresh_token"] == "refresh-token"
        assert result["token_type"] == "Bearer"
        assert result["mfa_required"] is False
        assert result["user"] is user
        user_id, created_tenant, session_id = harness.token_svc.pairs_created[0]
        assert (user_id, created_tenant) == (str(user.id), tenant_ctx)
        assert session_id is not None
        assert harness.session_svc.prior_device_checks == [(user.id, None, None)]
        assert [s.id for s in harness.session_svc.created] == [uuid.UUID(session_id)]
        assert harness.session_svc.created[0].user_id == user.id
        assert harness.session_svc.created[0].tenant_id == uuid.UUID(tenant_ctx)
        assert harness.audit_svc.events == [
            {
                "action": "auth.login.success",
                "target": f"user:{user.id}",
                "user_id": str(user.id),
                "tenant_id": None,
            }
        ]
        assert harness.email_svc.sent == []

    async def test_new_device_sends_security_alert(self, tenant_ctx: str) -> None:
        user = _make_user()
        harness = _Harness(users=[user], prior_device=False)

        await harness.service.login(
            LoginRequest(email=user.email, password="Password1!"),
            ip_address="203.0.113.7",
            user_agent="Mozilla/5.0 (X11; Linux x86_64)",
        )

        assert harness.email_svc.sent == [
            {
                "to": user.email,
                "full_name": "Test User",
                "event_type": "new_device",
                "ip_address": "203.0.113.7",
                "user_agent": "Mozilla/5.0 (X11; Linux x86_64)",
            }
        ]

    async def test_unverified_user_raises(self, tenant_ctx: str) -> None:
        user = _make_user(is_verified=False)
        harness = _Harness(users=[user])

        with pytest.raises(AuthenticationError):
            await harness.service.login(LoginRequest(email=user.email, password="Password1!"))

        assert harness.token_svc.pairs_created == []
        assert harness.audit_svc.events == [
            {
                "action": "auth.login.failed",
                "target": f"user:{user.id}",
                "user_id": str(user.id),
                "tenant_id": tenant_ctx,
            }
        ]

    async def test_tenant_owner_without_mfa_requires_mfa(self, tenant_ctx: str) -> None:
        user = _make_user()
        harness = _Harness(users=[user], roles_for_user={user.id: ["tenant_owner"]})

        result = await harness.service.login(LoginRequest(email=user.email, password="Password1!"))

        assert result["mfa_required"] is True

    async def test_tenant_owner_with_mfa_not_required(self, tenant_ctx: str) -> None:
        user = _make_user(mfa_enabled=True)
        harness = _Harness(users=[user], roles_for_user={user.id: ["tenant_owner"]})

        result = await harness.service.login(LoginRequest(email=user.email, password="Password1!"))

        assert result["mfa_required"] is False

    async def test_unknown_email_raises(self, tenant_ctx: str) -> None:
        harness = _Harness()

        with pytest.raises(AuthenticationError) as excinfo:
            await harness.service.login(
                LoginRequest(email="nobody@example.com", password="Password1!")
            )

        assert excinfo.value.message == LOGIN_FAILED_MESSAGE
        assert harness.token_svc.pairs_created == []
        assert harness.audit_svc.events == [
            {
                "action": "auth.login.failed",
                "target": "email:nobody@example.com",
                "user_id": None,
                "tenant_id": tenant_ctx,
            }
        ]

    async def test_disabled_user_raises(self, tenant_ctx: str) -> None:
        user = _make_user(is_active=False)
        harness = _Harness(users=[user])

        with pytest.raises(AuthenticationError) as excinfo:
            await harness.service.login(LoginRequest(email=user.email, password="Password1!"))

        assert excinfo.value.message == LOGIN_FAILED_MESSAGE
        assert harness.token_svc.pairs_created == []
        assert harness.audit_svc.events == [
            {
                "action": "auth.login.failed",
                "target": f"user:{user.id}",
                "user_id": str(user.id),
                "tenant_id": tenant_ctx,
            }
        ]

    async def test_wrong_password_raises(self, tenant_ctx: str) -> None:
        user = _make_user()
        harness = _Harness(users=[user])

        with pytest.raises(AuthenticationError) as excinfo:
            await harness.service.login(LoginRequest(email=user.email, password="WrongPass1!"))

        assert excinfo.value.message == LOGIN_FAILED_MESSAGE
        assert harness.token_svc.pairs_created == []
        assert harness.audit_svc.events == [
            {
                "action": "auth.login.failed",
                "target": f"user:{user.id}",
                "user_id": str(user.id),
                "tenant_id": tenant_ctx,
            }
        ]

    async def test_all_failure_modes_raise_the_same_error(self, tenant_ctx: str) -> None:
        """Anti-enumeration invariant: every login failure is indistinguishable.

        Same exception type, same message — no account-existence oracle via
        error semantics.
        """
        disabled_user = _make_user(is_active=False)
        unverified_user = _make_user(is_verified=False)
        valid_user = _make_user()

        failures: list[tuple[_Harness, LoginRequest]] = [
            (_Harness(), LoginRequest(email="nobody@example.com", password="Password1!")),
            (
                _Harness(users=[disabled_user]),
                LoginRequest(email=disabled_user.email, password="Password1!"),
            ),
            (
                _Harness(users=[unverified_user]),
                LoginRequest(email=unverified_user.email, password="Password1!"),
            ),
            (
                _Harness(users=[valid_user]),
                LoginRequest(email=valid_user.email, password="WrongPass1!"),
            ),
        ]

        seen: set[tuple[type, str]] = set()
        for harness, request in failures:
            with pytest.raises(AuthenticationError) as excinfo:
                await harness.service.login(request)
            seen.add((type(excinfo.value), excinfo.value.message))

        assert seen == {(AuthenticationError, LOGIN_FAILED_MESSAGE)}


class TestRegister:
    async def test_provisions_tenant_roles_and_owner(self) -> None:
        harness = _Harness()

        result = await harness.service.register(
            RegisterRequest(
                email="owner@neworg.com",
                password="Password1!",
                full_name="New Owner",
                organization_name="Acme Inc",
            )
        )

        assert len(harness.tenant_repo.created) == 1
        tenant = harness.tenant_repo.created[0]
        assert tenant.name == "Acme Inc"
        assert tenant.slug == "acme-inc"
        assert tenant.is_active is True

        assert {role.name for role in harness.role_repo.created} == {
            name for name, _ in SYSTEM_ROLE_DEFINITIONS
        }
        assert len(harness.role_repo.created) == len(SYSTEM_ROLE_DEFINITIONS)
        for role in harness.role_repo.created:
            assert role.tenant_id == tenant.id
            assert role.is_system_role is True

        assert len(harness.user_repo.created) == 1
        user = harness.user_repo.created[0]
        assert user.email == "owner@neworg.com"
        assert user.full_name == "New Owner"
        assert user.is_active is True
        assert user.is_verified is False
        assert user.tenant_id == tenant.id

        owner_role = harness.role_repo.created[0]
        assert harness.role_repo.grants == [
            (str(user.id), str(owner_role.id), str(tenant.id), str(tenant.id))
        ]

        assert result["email"] == "owner@neworg.com"
        assert result["user_id"] == user.id
        assert result["tenant_id"] == tenant.id
        assert result["tenant_slug"] == "acme-inc"
        assert result["verification_pending"] is True
        assert result["verification_token"] is not None
        assert result["expires_in"] == settings.VERIFICATION_TOKEN_EXPIRE_MINUTES * 60

        assert harness.token_svc.pairs_created == []
        assert harness.audit_svc.events == [
            {
                "action": "auth.register.success",
                "target": f"user:{user.id}",
                "user_id": str(user.id),
                "tenant_id": str(tenant.id),
            }
        ]
        assert len(harness.email_svc.sent) == 1
        assert harness.email_svc.sent[0]["to"] == "owner@neworg.com"
        assert harness.email_svc.sent[0]["token"] == result["verification_token"]

    async def test_slug_collision_is_suffixed(self) -> None:
        existing = Tenant(name="Acme", slug="acme", id=uuid.uuid4())
        harness = _Harness(tenants=[existing])

        result = await harness.service.register(
            RegisterRequest(
                email="owner@acme.com",
                password="Password1!",
                full_name="Acme Owner",
                organization_name="Acme",
            )
        )

        assert result["tenant_slug"] == "acme-2"

    async def test_register_ignores_taken_email(self) -> None:
        taken = _make_user(tenant_id=uuid.uuid4(), email="taken@example.com")
        harness = _Harness(users=[taken])

        result = await harness.service.register(
            RegisterRequest(
                email="taken@example.com",
                password="Password1!",
                full_name="Dup",
                organization_name="Another Org",
            )
        )

        assert result["verification_pending"] is True
        assert len(harness.user_repo.created) == 1


class TestVerifyEmail:
    async def test_valid_token_marks_user_verified_and_is_idempotent(self) -> None:
        user = _make_user(tenant_id=uuid.uuid4(), is_verified=False)
        harness = _Harness(users=[user])
        token = create_email_verification_token(str(user.id), tenant_id=str(user.tenant_id))

        await harness.service.verify_email(token)
        assert user.is_verified is True

        await harness.service.verify_email(token)
        assert user.is_verified is True

    async def test_wrong_token_type_raises(self) -> None:
        user = _make_user(tenant_id=uuid.uuid4(), is_verified=False)
        harness = _Harness(users=[user])
        token = create_access_token(str(user.id), tenant_id=str(user.tenant_id))

        with pytest.raises(TokenInvalidError):
            await harness.service.verify_email(token)

        assert user.is_verified is False

    async def test_tenant_mismatch_raises(self) -> None:
        user = _make_user(tenant_id=uuid.uuid4(), is_verified=False)
        harness = _Harness(users=[user])
        token = create_email_verification_token(str(user.id), tenant_id=str(uuid.uuid4()))

        with pytest.raises(TokenInvalidError):
            await harness.service.verify_email(token)

        assert user.is_verified is False
