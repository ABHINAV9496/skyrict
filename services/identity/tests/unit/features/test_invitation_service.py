"""Unit tests for the invitation feature InvitationService (fake ports)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from identity.core.constants import DEFAULT_INVITE_ROLE
from identity.core.security import hash_invitation_token
from identity.domain.entities import Invitation, Membership, MembershipStatus, Role, User
from identity.features.invitations.service import InvitationService
from skyrict_common.exceptions import (
    InvitationAlreadyUsedError,
    InvitationEmailMismatchError,
    InvitationExpiredError,
    InvitationNotFoundError,
    NotFoundError,
    UserAlreadyExistsError,
    ValidationError,
)


class FakeInvitationRepo:
    def __init__(self) -> None:
        self.invitations: dict[uuid.UUID, Invitation] = {}
        self.used: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def create(self, invitation: Invitation) -> Invitation:
        if invitation.id is None:
            invitation.id = uuid.uuid4()
        self.invitations[invitation.id] = invitation
        return invitation

    async def get_by_token(self, token: str) -> Invitation | None:
        token_hash = hash_invitation_token(token)
        for inv in self.invitations.values():
            if inv.token_hash == token_hash:
                return inv
        return None

    async def mark_used(
        self, invitation_id: str | uuid.UUID, user_id: str | uuid.UUID | None
    ) -> Invitation:
        inv = self.invitations.get(uuid.UUID(str(invitation_id)))
        if inv is None:
            raise NotFoundError("Invitation not found")
        inv.used_at = datetime.now(UTC)
        inv.used_by_user_id = uuid.UUID(str(user_id)) if user_id else None
        if user_id is not None:
            self.used.append((inv.id, uuid.UUID(str(user_id))))
        return inv

    async def list_by_tenant(
        self, tenant_id: str | uuid.UUID, *, offset: int = 0, limit: int = 20
    ) -> list[Invitation]:
        return [inv for inv in self.invitations.values() if str(inv.tenant_id) == str(tenant_id)]


class FakeUserRepo:
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}
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

    async def update_profile(self, user_id: str | uuid.UUID, **kwargs: object) -> User:
        raise NotImplementedError

    async def update_password_hash(self, user_id: str | uuid.UUID, password_hash: str) -> User:
        raise NotImplementedError

    async def mark_verified(self, user_id: str | uuid.UUID) -> User:
        raise NotImplementedError


class FakeRoleRepo:
    def __init__(self) -> None:
        self.roles: dict[uuid.UUID, Role] = {}
        self.grants: list[dict[str, object]] = []

    async def create(self, role: Role) -> Role:
        if role.id is None:
            role.id = uuid.uuid4()
        self.roles[role.id] = role
        return role

    async def get_by_id(self, role_id: str | uuid.UUID) -> Role | None:
        return self.roles.get(uuid.UUID(str(role_id)))

    async def get_by_name(self, tenant_id: str | uuid.UUID, name: str) -> Role | None:
        for role in self.roles.values():
            if role.name == name and str(role.tenant_id) == str(tenant_id):
                return role
        return None

    async def list_by_tenant(
        self, tenant_id: str | uuid.UUID, *, offset: int = 0, limit: int = 20
    ) -> list[Role]:
        return [r for r in self.roles.values() if str(r.tenant_id) == str(tenant_id)]

    async def grant_to_user(
        self,
        *,
        user_id: str | uuid.UUID,
        role_id: str | uuid.UUID,
        tenant_id: str | uuid.UUID,
        scope_id: str | uuid.UUID,
        scope_type: object = None,
    ) -> None:
        self.grants.append(
            {
                "user_id": str(user_id),
                "role_id": str(role_id),
                "tenant_id": str(tenant_id),
                "scope_id": str(scope_id),
            }
        )

    async def get_roles_for_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID
    ) -> list[str]:
        return []


class FakeEmailService:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send_verification(
        self, *, to: str, full_name: str, token: str, base_url: str | None = None
    ) -> None:
        pass

    async def send_invitation(
        self,
        *,
        to: str,
        inviter_name: str,
        organization_name: str,
        token: str,
        base_url: str | None = None,
    ) -> None:
        self.sent.append({"to": to, "token": token})


class FakeAuditService:
    """In-memory AuditService double capturing recorded entries."""

    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    async def log(self, *, action: str, target: str, **kwargs: object) -> None:
        self.entries.append({"action": action, "target": target, **kwargs})


class FakeMembershipService:
    def __init__(self) -> None:
        self.invited: list[Membership] = []
        self.activated: list[tuple[uuid.UUID, uuid.UUID]] = []
        self.active: list[Membership] = []

    async def create_invited(
        self,
        *,
        tenant_id: str | uuid.UUID,
        email: str,
        role_id: str | uuid.UUID,
        invited_by_user_id: str | uuid.UUID,
    ) -> Membership:
        membership = Membership(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(str(tenant_id)),
            invited_email=email.strip().lower(),
            status=MembershipStatus.INVITED,
            role_id=uuid.UUID(str(role_id)),
            invited_by_user_id=uuid.UUID(str(invited_by_user_id)),
            invited_at=datetime.now(UTC),
        )
        self.invited.append(membership)
        return membership

    async def create_active(
        self,
        *,
        tenant_id: str | uuid.UUID,
        user_id: str | uuid.UUID,
        role_id: str | uuid.UUID | None = None,
        invited_email: str | None = None,
    ) -> Membership:
        membership = Membership(
            id=uuid.uuid4(),
            tenant_id=uuid.UUID(str(tenant_id)),
            user_id=uuid.UUID(str(user_id)),
            invited_email=invited_email.strip().lower() if invited_email else None,
            role_id=uuid.UUID(str(role_id)) if role_id is not None else None,
            status=MembershipStatus.ACTIVE,
            joined_at=datetime.now(UTC),
        )
        self.active.append(membership)
        return membership

    async def activate(
        self,
        *,
        membership_id: str | uuid.UUID,
        user_id: str | uuid.UUID,
    ) -> Membership:
        self.activated.append((uuid.UUID(str(membership_id)), uuid.UUID(str(user_id))))
        membership = next((m for m in self.invited if m.id == uuid.UUID(str(membership_id))), None)
        if membership is None:
            raise NotFoundError("Membership not found")
        membership.status = MembershipStatus.ACTIVE
        membership.user_id = uuid.UUID(str(user_id))
        membership.joined_at = datetime.now(UTC)
        return membership


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def repos() -> tuple[
    FakeInvitationRepo,
    FakeUserRepo,
    FakeRoleRepo,
    FakeEmailService,
    FakeMembershipService,
]:
    return (
        FakeInvitationRepo(),
        FakeUserRepo(),
        FakeRoleRepo(),
        FakeEmailService(),
        FakeMembershipService(),
    )


@pytest.fixture
def audit() -> FakeAuditService:
    return FakeAuditService()


@pytest.fixture
def service(
    repos: tuple[
        FakeInvitationRepo,
        FakeUserRepo,
        FakeRoleRepo,
        FakeEmailService,
        FakeMembershipService,
    ],
    audit: FakeAuditService,
) -> InvitationService:
    inv_repo, user_repo, role_repo, email, membership_service = repos
    return InvitationService(inv_repo, user_repo, role_repo, email, membership_service, audit)


class TestCreateInvitation:
    async def test_creates_invitation_and_sends_email(
        self,
        service: InvitationService,
        repos: tuple,
        audit: FakeAuditService,
        tenant_id: uuid.UUID,
    ) -> None:
        _, _, role_repo, email, membership_service = repos
        inviter_id = uuid.uuid4()
        await role_repo.create(
            Role(tenant_id=tenant_id, name=DEFAULT_INVITE_ROLE, permissions=["users:read"])
        )

        invitation, token = await service.create_invitation(
            tenant_id=tenant_id,
            email="new@test.com",
            role_name=DEFAULT_INVITE_ROLE,
            created_by_user_id=inviter_id,
            inviter_name="Admin",
            organization_name="Test Corp",
        )

        assert invitation.id is not None
        assert invitation.email == "new@test.com"
        assert invitation.tenant_id == tenant_id
        assert invitation.created_by_user_id == inviter_id
        assert invitation.expires_at > datetime.now(UTC)
        assert invitation.role_name == DEFAULT_INVITE_ROLE
        assert invitation.token_hash == hash_invitation_token(token)
        assert token
        assert len(email.sent) == 1
        assert email.sent[0]["to"] == "new@test.com"

        assert len(membership_service.invited) == 1
        invited = membership_service.invited[0]
        assert invited.status == MembershipStatus.INVITED
        assert invited.invited_email == "new@test.com"
        assert invited.tenant_id == tenant_id
        assert invited.invited_by_user_id == inviter_id
        assert invitation.membership_id == invited.id

        actions = [entry["action"] for entry in audit.entries]
        assert actions == ["invitation.created"]
        assert audit.entries[0]["target"] == f"invitation:{invitation.id}"
        assert audit.entries[0]["tenant_id"] == str(tenant_id)
        assert audit.entries[0]["user_id"] == str(inviter_id)

    async def test_create_rejects_unknown_role(
        self, service: InvitationService, repos: tuple, tenant_id: uuid.UUID
    ) -> None:
        with pytest.raises(ValidationError):
            await service.create_invitation(
                tenant_id=tenant_id,
                email="new@test.com",
                role_name="viewer",
                created_by_user_id=uuid.uuid4(),
            )


class TestAcceptInvitation:
    async def test_accept_grants_invitation_role(
        self,
        service: InvitationService,
        repos: tuple,
        audit: FakeAuditService,
        tenant_id: uuid.UUID,
    ) -> None:
        inv_repo, _, role_repo, _, membership_service = repos

        standard_role = await role_repo.create(
            Role(tenant_id=tenant_id, name=DEFAULT_INVITE_ROLE, permissions=["users:read"])
        )

        invitation = await inv_repo.create(
            Invitation(
                tenant_id=tenant_id,
                email="invitee@test.com",
                token_hash=hash_invitation_token("valid-token-123"),
                role_name=DEFAULT_INVITE_ROLE,
                created_by_user_id=uuid.uuid4(),
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )

        user = await service.accept_invitation(
            token="valid-token-123",
            email="invitee@test.com",
            password="SecurePass123!",
            full_name="Invitee User",
        )

        assert user.id is not None
        assert user.email == "invitee@test.com"
        assert user.is_verified is True
        assert user.is_active is True
        assert len(role_repo.grants) == 1
        assert role_repo.grants[0]["role_id"] == str(standard_role.id)
        assert inv_repo.invitations[invitation.id].used_at is not None

        assert len(membership_service.active) == 1
        assert membership_service.active[0].user_id == user.id
        assert membership_service.active[0].status == MembershipStatus.ACTIVE

        actions = [entry["action"] for entry in audit.entries]
        assert actions == ["invitation.accepted"]
        assert audit.entries[0]["target"] == f"invitation:{invitation.id}"
        assert audit.entries[0]["tenant_id"] == str(tenant_id)
        assert audit.entries[0]["user_id"] == str(user.id)

    async def test_accept_activates_linked_membership(
        self,
        service: InvitationService,
        repos: tuple,
        audit: FakeAuditService,
        tenant_id: uuid.UUID,
    ) -> None:
        inv_repo, _, role_repo, _, membership_service = repos

        standard_role = await role_repo.create(
            Role(tenant_id=tenant_id, name=DEFAULT_INVITE_ROLE, permissions=["users:read"])
        )
        pending = await membership_service.create_invited(
            tenant_id=tenant_id,
            email="linked@test.com",
            role_id=standard_role.id,
            invited_by_user_id=uuid.uuid4(),
        )
        invitation = await inv_repo.create(
            Invitation(
                tenant_id=tenant_id,
                email="linked@test.com",
                token_hash=hash_invitation_token("linked-token"),
                role_name=DEFAULT_INVITE_ROLE,
                created_by_user_id=uuid.uuid4(),
                expires_at=datetime.now(UTC) + timedelta(days=7),
                membership_id=pending.id,
            )
        )

        user = await service.accept_invitation(
            token="linked-token",
            email="linked@test.com",
            password="SecurePass123!",
            full_name="Linked User",
        )

        assert membership_service.activated == [(pending.id, user.id)]
        assert membership_service.active == []
        assert inv_repo.invitations[invitation.id].used_at is not None

        actions = [entry["action"] for entry in audit.entries]
        assert actions == ["invitation.accepted"]
        assert audit.entries[0]["target"] == f"invitation:{invitation.id}"
        assert audit.entries[0]["tenant_id"] == str(tenant_id)
        assert audit.entries[0]["user_id"] == str(user.id)

    async def test_accept_missing_invitation_role_raises(
        self, service: InvitationService, repos: tuple, tenant_id: uuid.UUID
    ) -> None:
        inv_repo, *_ = repos
        await inv_repo.create(
            Invitation(
                tenant_id=tenant_id,
                email="roless@test.com",
                token_hash=hash_invitation_token("roless-token"),
                role_name="ghost-role",
                created_by_user_id=uuid.uuid4(),
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )

        with pytest.raises(ValidationError):
            await service.accept_invitation(
                token="roless-token",
                email="roless@test.com",
                password="SecurePass123!",
                full_name="Roleless User",
            )

    async def test_accept_expired_token_raises(
        self, service: InvitationService, repos: tuple, tenant_id: uuid.UUID
    ) -> None:
        inv_repo, *_ = repos
        await inv_repo.create(
            Invitation(
                tenant_id=tenant_id,
                email="expired@test.com",
                token_hash=hash_invitation_token("expired-token"),
                role_name=DEFAULT_INVITE_ROLE,
                created_by_user_id=uuid.uuid4(),
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
        )

        with pytest.raises(InvitationExpiredError):
            await service.accept_invitation(
                token="expired-token",
                email="expired@test.com",
                password="SecurePass123!",
                full_name="Expired User",
            )

    async def test_accept_already_used_token_raises(
        self, service: InvitationService, repos: tuple, tenant_id: uuid.UUID
    ) -> None:
        inv_repo, *_ = repos
        invitation = await inv_repo.create(
            Invitation(
                tenant_id=tenant_id,
                email="used@test.com",
                token_hash=hash_invitation_token("used-token"),
                role_name=DEFAULT_INVITE_ROLE,
                created_by_user_id=uuid.uuid4(),
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
        await inv_repo.mark_used(invitation.id, uuid.uuid4())

        with pytest.raises(InvitationAlreadyUsedError):
            await service.accept_invitation(
                token="used-token",
                email="used@test.com",
                password="SecurePass123!",
                full_name="Used User",
            )

    async def test_accept_email_mismatch_raises(
        self, service: InvitationService, repos: tuple, tenant_id: uuid.UUID
    ) -> None:
        inv_repo, *_ = repos
        await inv_repo.create(
            Invitation(
                tenant_id=tenant_id,
                email="original@test.com",
                token_hash=hash_invitation_token("mismatch-token"),
                role_name=DEFAULT_INVITE_ROLE,
                created_by_user_id=uuid.uuid4(),
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )

        with pytest.raises(InvitationEmailMismatchError):
            await service.accept_invitation(
                token="mismatch-token",
                email="wrong@test.com",
                password="SecurePass123!",
                full_name="Wrong Email",
            )

    async def test_accept_unknown_token_raises(
        self, service: InvitationService, repos: tuple, tenant_id: uuid.UUID
    ) -> None:
        with pytest.raises(InvitationNotFoundError):
            await service.accept_invitation(
                token="nonexistent-token",
                email="nobody@test.com",
                password="SecurePass123!",
                full_name="Nobody",
            )

    async def test_accept_existing_user_raises(
        self, service: InvitationService, repos: tuple, tenant_id: uuid.UUID
    ) -> None:
        inv_repo, user_repo, *_ = repos
        existing_user = User(
            tenant_id=tenant_id,
            email="exists@test.com",
            password_hash="hash",
            full_name="Existing",
        )
        await user_repo.create(existing_user)

        await inv_repo.create(
            Invitation(
                tenant_id=tenant_id,
                email="exists@test.com",
                token_hash=hash_invitation_token("existing-user-token"),
                role_name=DEFAULT_INVITE_ROLE,
                created_by_user_id=uuid.uuid4(),
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )

        with pytest.raises(UserAlreadyExistsError):
            await service.accept_invitation(
                token="existing-user-token",
                email="exists@test.com",
                password="SecurePass123!",
                full_name="Existing User",
            )


class TestExpireInvitation:
    async def test_expire_marks_as_used(
        self,
        service: InvitationService,
        repos: tuple,
        audit: FakeAuditService,
        tenant_id: uuid.UUID,
    ) -> None:
        inv_repo, *_ = repos
        invitation = await inv_repo.create(
            Invitation(
                tenant_id=tenant_id,
                email="to-expire@test.com",
                token_hash=hash_invitation_token("expire-token"),
                role_name=DEFAULT_INVITE_ROLE,
                created_by_user_id=uuid.uuid4(),
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )

        await service.expire_invitation(invitation.id, tenant_id)
        assert inv_repo.invitations[invitation.id].used_at is not None

        actions = [entry["action"] for entry in audit.entries]
        assert actions == ["invitation.expired"]
        assert audit.entries[0]["target"] == f"invitation:{invitation.id}"
        assert audit.entries[0]["tenant_id"] == str(tenant_id)

    async def test_expire_unknown_raises(
        self, service: InvitationService, repos: tuple, tenant_id: uuid.UUID
    ) -> None:
        with pytest.raises(InvitationNotFoundError):
            await service.expire_invitation(uuid.uuid4(), tenant_id)


class TestListInvitations:
    async def test_returns_only_this_tenant_invitations(
        self,
        service: InvitationService,
        repos: tuple,
        tenant_id: uuid.UUID,
    ) -> None:
        inv_repo, *_ = repos
        other_tenant_id = uuid.uuid4()

        def _make(tenant: uuid.UUID, email: str) -> Invitation:
            return Invitation(
                tenant_id=tenant,
                email=email,
                token_hash=hash_invitation_token(email),
                role_name=DEFAULT_INVITE_ROLE,
                created_by_user_id=uuid.uuid4(),
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )

        own = _make(tenant_id, "own@test.com")
        other = _make(other_tenant_id, "other@test.com")
        await inv_repo.create(own)
        await inv_repo.create(other)

        result = await service.list_invitations(tenant_id)

        assert result == [own]
        assert other not in result
