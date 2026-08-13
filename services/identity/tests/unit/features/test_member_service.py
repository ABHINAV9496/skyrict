"""Unit tests for the member management feature MemberService (fake ports)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from identity.domain.entities import Membership, MembershipStatus, Role, Session, User
from identity.features.members.service import MemberService
from skyrict_common.exceptions import UserNotFoundError, ValidationError

if TYPE_CHECKING:
    from identity.features.members.schemas import MemberResponse


class FakeAuditService:
    """In-memory AuditService double capturing recorded entries."""

    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    async def log(self, *, action: str, target: str, **kwargs: object) -> None:
        self.entries.append({"action": action, "target": target, **kwargs})


class FakeUserRepo:
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}
        self.deactivated: list[uuid.UUID] = []

    def add(self, user: User) -> User:
        assert user.id is not None
        self.users[user.id] = user
        return user

    async def get_by_id(self, user_id: str | uuid.UUID) -> User | None:
        return self.users.get(uuid.UUID(str(user_id)))

    async def set_active(self, user_id: str | uuid.UUID, *, is_active: bool) -> User:
        key = uuid.UUID(str(user_id))
        self.users[key].is_active = is_active
        self.deactivated.append(key)
        return self.users[key]


class FakeMembershipService:
    def __init__(self) -> None:
        self.memberships: list[Membership] = []
        self.role_updates: list[tuple[uuid.UUID, uuid.UUID]] = []
        self.suspended: list[uuid.UUID] = []
        self.suspend_error: Exception | None = None

    def add(self, membership: Membership) -> Membership:
        assert membership.id is not None
        self.memberships.append(membership)
        return membership

    async def list_members(
        self,
        tenant_id: str | uuid.UUID,
        *,
        status: MembershipStatus | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[Membership]:
        rows = [
            m
            for m in self.memberships
            if str(m.tenant_id) == str(tenant_id) and (status is None or m.status is status)
        ]
        return rows[offset : offset + limit]

    async def get_by_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID
    ) -> Membership | None:
        for membership in self.memberships:
            if str(membership.user_id) == str(user_id) and str(membership.tenant_id) == str(
                tenant_id
            ):
                return membership
        return None

    async def update_role(
        self, *, membership_id: str | uuid.UUID, role_id: str | uuid.UUID
    ) -> Membership:
        self.role_updates.append((uuid.UUID(str(membership_id)), uuid.UUID(str(role_id))))
        membership = next(m for m in self.memberships if str(m.id) == str(membership_id))
        membership.role_id = uuid.UUID(str(role_id))
        return membership

    async def suspend(self, *, membership_id: str | uuid.UUID) -> Membership:
        if self.suspend_error is not None:
            raise self.suspend_error
        membership = next(m for m in self.memberships if str(m.id) == str(membership_id))
        membership.status = MembershipStatus.SUSPENDED
        self.suspended.append(membership.id)  # type: ignore[arg-type]
        return membership


class FakeRoleRepo:
    def __init__(self) -> None:
        self.roles: dict[uuid.UUID, Role] = {}
        self.grants: dict[uuid.UUID, list[uuid.UUID]] = {}
        self.revoked: list[uuid.UUID] = []

    def add(self, role: Role) -> Role:
        assert role.id is not None
        self.roles[role.id] = role
        return role

    def grant(self, user_id: uuid.UUID, role_id: uuid.UUID) -> None:
        self.grants.setdefault(user_id, []).append(role_id)

    async def get_by_id(self, role_id: str | uuid.UUID) -> Role | None:
        return self.roles.get(uuid.UUID(str(role_id)))

    async def get_by_name(self, tenant_id: str | uuid.UUID, name: str) -> Role | None:
        for role in self.roles.values():
            if role.name == name and str(role.tenant_id) == str(tenant_id):
                return role
        return None

    async def get_roles_for_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID
    ) -> list[str]:
        role_ids = self.grants.get(uuid.UUID(str(user_id)), [])
        return [
            self.roles[role_id].name
            for role_id in role_ids
            if role_id in self.roles and str(self.roles[role_id].tenant_id) == str(tenant_id)
        ]

    async def count_users_with_role(self, tenant_id: str | uuid.UUID, role_name: str) -> int:
        return sum(
            1
            for user_id, role_ids in self.grants.items()
            if any(
                role_id in self.roles
                and self.roles[role_id].name == role_name
                and str(self.roles[role_id].tenant_id) == str(tenant_id)
                for role_id in role_ids
            )
            for _ in [0]
        )

    async def revoke_all_for_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID
    ) -> None:
        key = uuid.UUID(str(user_id))
        self.revoked.append(key)
        self.grants.pop(key, None)

    async def grant_to_user(
        self,
        *,
        user_id: str | uuid.UUID,
        role_id: str | uuid.UUID,
        tenant_id: str | uuid.UUID,
        scope_id: str | uuid.UUID,
        **kwargs: object,
    ) -> None:
        self.grant(uuid.UUID(str(user_id)), uuid.UUID(str(role_id)))


class FakeSessionService:
    def __init__(self) -> None:
        self.revoked: list[uuid.UUID] = []
        self.revoked_sessions: list[uuid.UUID] = []
        self.sessions: list[Session] = []
        self.list_calls: list[tuple[uuid.UUID, uuid.UUID | None]] = []

    def add_session(self, session: Session) -> Session:
        self.sessions.append(session)
        return session

    async def list_user_sessions(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID | None = None
    ) -> list[Session]:
        self.list_calls.append((uuid.UUID(str(user_id)), tenant_id))
        return [
            s
            for s in self.sessions
            if str(s.user_id) == str(user_id) and (tenant_id is None or str(s.tenant_id) == str(tenant_id))
        ]

    async def revoke_all_sessions(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID | None = None
    ) -> None:
        self.revoked.append(uuid.UUID(str(user_id)))

    async def revoke_session(
        self,
        user_id: str | uuid.UUID,
        session_id: str | uuid.UUID,
        tenant_id: str | uuid.UUID | None = None,
    ) -> None:
        self.revoked_sessions.append(uuid.UUID(str(session_id)))


def _user(tenant_id: uuid.UUID, *, name: str = "Ada Lovelace") -> User:
    return User(
        tenant_id=tenant_id,
        email=f"{name.lower().replace(' ', '.')}@acme.io",
        password_hash="x",
        full_name=name,
        id=uuid.uuid4(),
    )


def _role(tenant_id: uuid.UUID, name: str) -> Role:
    return Role(tenant_id=tenant_id, name=name, permissions=[], id=uuid.uuid4())


def _membership(
    tenant_id: uuid.UUID, user: User, role_id: uuid.UUID | None, joined: datetime
) -> Membership:
    return Membership(
        tenant_id=tenant_id,
        user_id=user.id,
        status=MembershipStatus.ACTIVE,
        role_id=role_id,
        joined_at=joined,
        id=uuid.uuid4(),
    )


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def audit() -> FakeAuditService:
    return FakeAuditService()


@pytest.fixture
def user_repo() -> FakeUserRepo:
    return FakeUserRepo()


@pytest.fixture
def membership_svc() -> FakeMembershipService:
    return FakeMembershipService()


@pytest.fixture
def role_repo() -> FakeRoleRepo:
    return FakeRoleRepo()


@pytest.fixture
def session_svc() -> FakeSessionService:
    return FakeSessionService()


@pytest.fixture
def service(
    user_repo: FakeUserRepo,
    membership_svc: FakeMembershipService,
    role_repo: FakeRoleRepo,
    session_svc: FakeSessionService,
    audit: FakeAuditService,
) -> MemberService:
    return MemberService(user_repo, membership_svc, role_repo, session_svc, audit)


async def test_list_members_resolves_role_and_join_date(
    service: MemberService,
    user_repo: FakeUserRepo,
    membership_svc: FakeMembershipService,
    role_repo: FakeRoleRepo,
    tenant_id: uuid.UUID,
) -> None:
    member = user_repo.add(_user(tenant_id, name="Grace Hopper"))
    manager = role_repo.add(_role(tenant_id, "department_manager"))
    membership_svc.add(
        _membership(tenant_id, member, manager.id, datetime.now(UTC) - timedelta(days=30))
    )

    rows = await service.list_members(tenant_id, viewer_id=member.id)

    assert len(rows) == 1
    row = rows[0]
    assert row.email == member.email
    assert row.full_name == "Grace Hopper"
    assert row.role_name == "department_manager"
    assert row.joined_at is not None
    assert row.is_self is True


async def test_list_members_marks_others_as_not_self(
    service: MemberService,
    user_repo: FakeUserRepo,
    membership_svc: FakeMembershipService,
    role_repo: FakeRoleRepo,
    tenant_id: uuid.UUID,
) -> None:
    member = user_repo.add(_user(tenant_id))
    viewer = uuid.uuid4()
    role = role_repo.add(_role(tenant_id, "standard_user"))
    membership_svc.add(_membership(tenant_id, member, role.id, datetime.now(UTC)))

    rows = await service.list_members(tenant_id, viewer_id=viewer)

    assert len(rows) == 1
    assert rows[0].is_self is False


async def test_list_members_skips_rows_without_a_user(
    service: MemberService,
    membership_svc: FakeMembershipService,
    tenant_id: uuid.UUID,
) -> None:
    orphan = Membership(
        tenant_id=tenant_id,
        user_id=None,
        invited_email="ghost@acme.io",
        status=MembershipStatus.INVITED,
        id=uuid.uuid4(),
    )
    membership_svc.add(orphan)

    rows = await service.list_members(tenant_id, viewer_id=uuid.uuid4())

    assert rows == []


async def test_list_members_orders_newest_first(
    service: MemberService,
    user_repo: FakeUserRepo,
    membership_svc: FakeMembershipService,
    role_repo: FakeRoleRepo,
    tenant_id: uuid.UUID,
) -> None:
    older = user_repo.add(_user(tenant_id, name="Older User"))
    newer = user_repo.add(_user(tenant_id, name="Newer User"))
    role = role_repo.add(_role(tenant_id, "standard_user"))
    membership_svc.add(
        _membership(tenant_id, older, role.id, datetime.now(UTC) - timedelta(days=10))
    )
    membership_svc.add(
        _membership(tenant_id, newer, role.id, datetime.now(UTC) - timedelta(days=2))
    )

    rows: list[MemberResponse] = await service.list_members(tenant_id, viewer_id=uuid.uuid4())

    assert [row.id for row in rows] == [newer.id, older.id]


async def test_change_role_replaces_grant_and_updates_membership(
    service: MemberService,
    user_repo: FakeUserRepo,
    membership_svc: FakeMembershipService,
    role_repo: FakeRoleRepo,
    session_svc: FakeSessionService,
    audit: FakeAuditService,
    tenant_id: uuid.UUID,
) -> None:
    member = user_repo.add(_user(tenant_id))
    old_role = role_repo.add(_role(tenant_id, "standard_user"))
    new_role = role_repo.add(_role(tenant_id, "department_manager"))
    role_repo.grant(member.id, old_role.id)
    membership = _membership(tenant_id, member, old_role.id, datetime.now(UTC))
    membership_svc.add(membership)

    await service.change_role(
        tenant_id=tenant_id,
        user_id=member.id,
        role_name="department_manager",
        actor_user_id=uuid.uuid4(),
    )

    assert role_repo.revoked == [member.id]
    assert role_repo.grants[member.id] == [new_role.id]
    assert membership_svc.role_updates == [(membership.id, new_role.id)]
    assert audit.entries[-1]["action"] == "member.role_updated"
    assert audit.entries[-1]["target"] == f"user:{member.id}"
    assert audit.entries[-1]["details"] == {"role": "department_manager"}


async def test_change_role_rejects_unknown_role(
    service: MemberService,
    user_repo: FakeUserRepo,
    role_repo: FakeRoleRepo,
    tenant_id: uuid.UUID,
) -> None:
    member = user_repo.add(_user(tenant_id))
    role_repo.add(_role(tenant_id, "standard_user"))

    with pytest.raises(ValidationError):
        await service.change_role(
            tenant_id=tenant_id,
            user_id=member.id,
            role_name="ghost_role",
            actor_user_id=uuid.uuid4(),
        )


async def test_change_role_rejects_demoting_last_owner(
    service: MemberService,
    user_repo: FakeUserRepo,
    membership_svc: FakeMembershipService,
    role_repo: FakeRoleRepo,
    tenant_id: uuid.UUID,
) -> None:
    owner = user_repo.add(_user(tenant_id, name="The Owner"))
    owner_role = role_repo.add(_role(tenant_id, "tenant_owner"))
    role_repo.grant(owner.id, owner_role.id)
    membership_svc.add(_membership(tenant_id, owner, owner_role.id, datetime.now(UTC)))

    with pytest.raises(ValidationError):
        await service.change_role(
            tenant_id=tenant_id,
            user_id=owner.id,
            role_name="standard_user",
            actor_user_id=uuid.uuid4(),
        )

    assert role_repo.grants[owner.id] == [owner_role.id]


async def test_remove_member_deactivates_revokes_and_suspends(
    service: MemberService,
    user_repo: FakeUserRepo,
    membership_svc: FakeMembershipService,
    role_repo: FakeRoleRepo,
    session_svc: FakeSessionService,
    audit: FakeAuditService,
    tenant_id: uuid.UUID,
) -> None:
    member = user_repo.add(_user(tenant_id))
    role = role_repo.add(_role(tenant_id, "standard_user"))
    role_repo.grant(member.id, role.id)
    membership = _membership(tenant_id, member, role.id, datetime.now(UTC))
    membership_svc.add(membership)
    actor = uuid.uuid4()

    await service.remove_member(tenant_id=tenant_id, user_id=member.id, actor_user_id=actor)

    assert user_repo.deactivated == [member.id]
    assert user_repo.users[member.id].is_active is False
    assert session_svc.revoked == [member.id]
    assert membership_svc.suspended == [membership.id]
    assert audit.entries[-1]["action"] == "member.removed"
    assert audit.entries[-1]["target"] == f"user:{member.id}"
    assert audit.entries[-1]["user_id"] == str(actor)


async def test_remove_member_cannot_remove_self(
    service: MemberService,
    user_repo: FakeUserRepo,
    tenant_id: uuid.UUID,
) -> None:
    member = user_repo.add(_user(tenant_id))

    with pytest.raises(ValidationError):
        await service.remove_member(tenant_id=tenant_id, user_id=member.id, actor_user_id=member.id)

    assert user_repo.deactivated == []


async def test_remove_member_cannot_remove_last_owner(
    service: MemberService,
    user_repo: FakeUserRepo,
    membership_svc: FakeMembershipService,
    role_repo: FakeRoleRepo,
    tenant_id: uuid.UUID,
) -> None:
    owner = user_repo.add(_user(tenant_id, name="The Owner"))
    owner_role = role_repo.add(_role(tenant_id, "tenant_owner"))
    role_repo.grant(owner.id, owner_role.id)
    membership_svc.add(_membership(tenant_id, owner, owner_role.id, datetime.now(UTC)))

    with pytest.raises(ValidationError):
        await service.remove_member(
            tenant_id=tenant_id, user_id=owner.id, actor_user_id=uuid.uuid4()
        )

    assert user_repo.deactivated == []


async def test_remove_member_unknown_user_raises(
    service: MemberService,
    tenant_id: uuid.UUID,
) -> None:
    with pytest.raises(UserNotFoundError):
        await service.remove_member(
            tenant_id=tenant_id, user_id=uuid.uuid4(), actor_user_id=uuid.uuid4()
        )


async def test_list_member_sessions_scopes_to_tenant(
    service: MemberService,
    user_repo: FakeUserRepo,
    membership_svc: FakeMembershipService,
    role_repo: FakeRoleRepo,
    session_svc: FakeSessionService,
    tenant_id: uuid.UUID,
) -> None:
    member = user_repo.add(_user(tenant_id))
    role = role_repo.add(_role(tenant_id, "standard_user"))
    membership_svc.add(_membership(tenant_id, member, role.id, datetime.now(UTC)))
    own_session = session_svc.add_session(
        Session(user_id=member.id, tenant_id=tenant_id, refresh_token_hash="x", id=uuid.uuid4())
    )
    session_svc.add_session(
        Session(
            user_id=member.id,
            tenant_id=uuid.uuid4(),
            refresh_token_hash="x",
            id=uuid.uuid4(),
        )
    )

    sessions = await service.list_member_sessions(tenant_id, member.id)

    assert [s.id for s in sessions] == [own_session.id]
    assert session_svc.list_calls == [(member.id, tenant_id)]


async def test_list_member_sessions_unknown_member_raises(
    service: MemberService,
    tenant_id: uuid.UUID,
) -> None:
    with pytest.raises(UserNotFoundError):
        await service.list_member_sessions(tenant_id, uuid.uuid4())


async def test_revoke_member_session_forwards_to_session_service(
    service: MemberService,
    user_repo: FakeUserRepo,
    membership_svc: FakeMembershipService,
    role_repo: FakeRoleRepo,
    session_svc: FakeSessionService,
    tenant_id: uuid.UUID,
) -> None:
    member = user_repo.add(_user(tenant_id))
    role = role_repo.add(_role(tenant_id, "standard_user"))
    membership_svc.add(_membership(tenant_id, member, role.id, datetime.now(UTC)))
    session_id = uuid.uuid4()

    await service.revoke_member_session(
        tenant_id=tenant_id,
        user_id=member.id,
        session_id=session_id,
        actor_user_id=uuid.uuid4(),
    )

    assert session_svc.revoked_sessions == [session_id]


async def test_revoke_all_member_sessions_logs_member_out(
    service: MemberService,
    user_repo: FakeUserRepo,
    membership_svc: FakeMembershipService,
    role_repo: FakeRoleRepo,
    session_svc: FakeSessionService,
    tenant_id: uuid.UUID,
) -> None:
    member = user_repo.add(_user(tenant_id))
    role = role_repo.add(_role(tenant_id, "standard_user"))
    membership_svc.add(_membership(tenant_id, member, role.id, datetime.now(UTC)))

    await service.revoke_all_member_sessions(
        tenant_id=tenant_id,
        user_id=member.id,
        actor_user_id=uuid.uuid4(),
    )

    assert session_svc.revoked == [member.id]


async def test_revoke_all_member_sessions_cannot_target_self(
    service: MemberService,
    user_repo: FakeUserRepo,
    membership_svc: FakeMembershipService,
    role_repo: FakeRoleRepo,
    session_svc: FakeSessionService,
    tenant_id: uuid.UUID,
) -> None:
    member = user_repo.add(_user(tenant_id))
    role = role_repo.add(_role(tenant_id, "tenant_owner"))
    role_repo.grant(member.id, role.id)
    membership_svc.add(_membership(tenant_id, member, role.id, datetime.now(UTC)))

    with pytest.raises(ValidationError):
        await service.revoke_all_member_sessions(
            tenant_id=tenant_id,
            user_id=member.id,
            actor_user_id=member.id,
        )

    assert session_svc.revoked == []
