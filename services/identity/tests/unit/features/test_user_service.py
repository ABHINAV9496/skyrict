"""Unit tests for the users feature service (fake UserRepositoryPort) and the
roles feature services (fake RoleRepositoryPort)."""

from __future__ import annotations

import uuid

import pytest

from identity.core.security import hash_password, verify_password
from identity.domain.entities import Role, ScopeType, User
from identity.features.roles.schemas import RoleCreateRequest
from identity.features.roles.service import AuthorizationService, RoleManagementService
from identity.features.users.schemas import UserUpdateRequest
from identity.features.users.service import UserService
from skyrict_common.exceptions import (
    AuthorizationError,
    InvalidPasswordError,
    NotFoundError,
    PermissionDeniedError,
    UserNotFoundError,
    ValidationError,
)


class FakeUserRepo:
    """In-memory UserRepositoryPort double."""

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


class FakeRoleRepo:
    """In-memory RoleRepositoryPort double, including the permission-resolution,
    update, delete, and grant-existence operations the services depend on."""

    def __init__(self, roles: list[Role] | None = None) -> None:
        self.roles: dict[uuid.UUID, Role] = {}
        for role in roles or []:
            if role.id is None:
                role.id = uuid.uuid4()
            self.roles[role.id] = role
        self.grants: list[dict[str, object]] = []
        self.deleted: list[uuid.UUID] = []

    async def create(self, role: Role) -> Role:
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
        roles = [role for role in self.roles.values() if str(role.tenant_id) == str(tenant_id)]
        roles.sort(key=lambda role: role.name)
        return roles[offset : offset + limit]

    async def grant_to_user(
        self,
        *,
        user_id: str | uuid.UUID,
        role_id: str | uuid.UUID,
        tenant_id: str | uuid.UUID,
        scope_id: str | uuid.UUID,
        scope_type: ScopeType = ScopeType.TENANT,
    ) -> None:
        self.grants.append(
            {
                "user_id": uuid.UUID(str(user_id)),
                "role_id": uuid.UUID(str(role_id)),
                "tenant_id": uuid.UUID(str(tenant_id)),
                "scope_id": uuid.UUID(str(scope_id)),
                "scope_type": scope_type,
            }
        )

    async def get_roles_for_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID
    ) -> list[str]:
        names: list[str] = []
        for grant in self.grants:
            if grant["user_id"] == uuid.UUID(str(user_id)) and grant["tenant_id"] == uuid.UUID(
                str(tenant_id)
            ):
                role = self.roles.get(grant["role_id"])
                if role is not None:
                    names.append(role.name)
        return names

    async def get_permissions_for_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID
    ) -> set[str]:
        permissions: set[str] = set()
        for grant in self.grants:
            if grant["user_id"] == uuid.UUID(str(user_id)) and grant["tenant_id"] == uuid.UUID(
                str(tenant_id)
            ):
                role = self.roles.get(grant["role_id"])
                if role is not None:
                    permissions.update(role.permissions)
        return permissions

    async def update(self, role: Role) -> Role:
        if role.id is not None:
            self.roles[role.id] = role
        return role

    async def delete(self, role_id: str | uuid.UUID) -> None:
        role_uuid = uuid.UUID(str(role_id))
        self.deleted.append(role_uuid)
        self.roles.pop(role_uuid, None)

    async def grant_exists(
        self,
        user_id: str | uuid.UUID,
        role_id: str | uuid.UUID,
        scope_type: ScopeType,
        scope_id: str | uuid.UUID,
    ) -> bool:
        return any(
            grant["user_id"] == uuid.UUID(str(user_id))
            and grant["role_id"] == uuid.UUID(str(role_id))
            and grant["scope_type"] == scope_type
            and grant["scope_id"] == uuid.UUID(str(scope_id))
            for grant in self.grants
        )


def _make_user(*, email: str = "user@example.com", password: str = "Password1!") -> User:
    return User(
        tenant_id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(password),
        full_name="Test User",
    )


def _make_role(
    *,
    name: str = "custom_role",
    permissions: list[str] | None = None,
    tenant_id: uuid.UUID | None = None,
    is_system_role: bool = False,
) -> Role:
    return Role(
        tenant_id=tenant_id or uuid.uuid4(),
        name=name,
        permissions=permissions or [],
        is_system_role=is_system_role,
    )


async def _grant(
    repo: FakeRoleRepo,
    *,
    user_id: str | uuid.UUID,
    role: Role,
    tenant_id: str | uuid.UUID,
) -> None:
    await repo.grant_to_user(
        user_id=user_id,
        role_id=role.id,
        tenant_id=tenant_id,
        scope_id=tenant_id,
        scope_type=ScopeType.TENANT,
    )


class TestGetProfile:
    async def test_returns_user_when_found(self) -> None:
        user = _make_user()
        repo = FakeUserRepo([user])
        service = UserService(repo)

        assert await service.get_profile(str(user.id)) is user

    async def test_raises_when_missing(self) -> None:
        service = UserService(FakeUserRepo())

        with pytest.raises(UserNotFoundError):
            await service.get_profile(uuid.uuid4())


class TestUpdateProfile:
    async def test_delegates_to_repo(self) -> None:
        user = _make_user()
        repo = FakeUserRepo([user])
        service = UserService(repo)

        updated = await service.update_profile(
            str(user.id), UserUpdateRequest(full_name="New Name")
        )

        assert updated.full_name == "New Name"
        assert updated is user


class TestChangePassword:
    async def test_updates_hash_when_current_password_is_correct(self) -> None:
        user = _make_user(password="OldPass1!")
        repo = FakeUserRepo([user])
        service = UserService(repo)

        await service.change_password(str(user.id), "OldPass1!", "NewPass1!")

        assert verify_password("NewPass1!", user.password_hash)

    async def test_raises_when_current_password_is_wrong(self) -> None:
        user = _make_user(password="OldPass1!")
        repo = FakeUserRepo([user])
        service = UserService(repo)

        with pytest.raises(InvalidPasswordError):
            await service.change_password(str(user.id), "WrongPass1!", "NewPass1!")

        assert verify_password("OldPass1!", user.password_hash)


class TestAuthorizationService:
    async def test_grants_when_permission_present(self) -> None:
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        role = _make_role(permissions=["roles:read"], tenant_id=tenant_id)
        repo = FakeRoleRepo([role])
        await _grant(repo, user_id=user_id, role=role, tenant_id=tenant_id)

        service = AuthorizationService(repo)
        result = await service.check_permission(
            user_is_active=True,
            user_id=user_id,
            permission="roles:read",
            tenant_id=tenant_id,
        )

        assert result is True

    async def test_denies_and_names_exact_missing_permission(self) -> None:
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        role = _make_role(permissions=["users:read"], tenant_id=tenant_id)
        repo = FakeRoleRepo([role])
        await _grant(repo, user_id=user_id, role=role, tenant_id=tenant_id)

        service = AuthorizationService(repo)
        with pytest.raises(PermissionDeniedError, match=r"roles:write"):
            await service.check_permission(
                user_is_active=True,
                user_id=user_id,
                permission="roles:write",
                tenant_id=tenant_id,
            )

    async def test_inactive_user_raises_authorization_error(self) -> None:
        tenant_id = uuid.uuid4()
        role = _make_role(permissions=["*"], tenant_id=tenant_id)
        repo = FakeRoleRepo([role])

        service = AuthorizationService(repo)
        with pytest.raises(AuthorizationError):
            await service.check_permission(
                user_is_active=False,
                user_id=uuid.uuid4(),
                permission="roles:write",
                tenant_id=tenant_id,
            )

    async def test_wildcard_grants_any_permission(self) -> None:
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        role = _make_role(permissions=["*"], tenant_id=tenant_id)
        repo = FakeRoleRepo([role])
        await _grant(repo, user_id=user_id, role=role, tenant_id=tenant_id)

        service = AuthorizationService(repo)
        result = await service.check_permission(
            user_is_active=True,
            user_id=user_id,
            permission="billing.manage",
            tenant_id=tenant_id,
        )

        assert result is True

    async def test_no_roles_fails_closed(self) -> None:
        tenant_id = uuid.uuid4()
        repo = FakeRoleRepo()

        service = AuthorizationService(repo)
        with pytest.raises(PermissionDeniedError, match=r"roles:write"):
            await service.check_permission(
                user_is_active=True,
                user_id=uuid.uuid4(),
                permission="roles:write",
                tenant_id=tenant_id,
            )

    async def test_empty_permissions_fails_closed(self) -> None:
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        role = _make_role(permissions=[], tenant_id=tenant_id)
        repo = FakeRoleRepo([role])
        await _grant(repo, user_id=user_id, role=role, tenant_id=tenant_id)

        service = AuthorizationService(repo)
        with pytest.raises(PermissionDeniedError, match=r"roles:write"):
            await service.check_permission(
                user_is_active=True,
                user_id=user_id,
                permission="roles:write",
                tenant_id=tenant_id,
            )

    async def test_require_permission_raises_on_denial(self) -> None:
        tenant_id = uuid.uuid4()
        repo = FakeRoleRepo()

        service = AuthorizationService(repo)
        with pytest.raises(PermissionDeniedError, match=r"roles:write"):
            await service.require_permission(
                user_is_active=True,
                user_id=uuid.uuid4(),
                permission="roles:write",
                tenant_id=tenant_id,
            )


class TestCreateCustomRole:
    async def test_rejects_reserved_system_name(self) -> None:
        service = RoleManagementService(FakeRoleRepo())

        with pytest.raises(ValidationError, match="reserved system role"):
            await service.create_custom_role(
                uuid.uuid4(), RoleCreateRequest(name="tenant_owner", permission_keys=["users:read"])
            )

    async def test_rejects_duplicate_name(self) -> None:
        tenant_id = uuid.uuid4()
        role = _make_role(name="ops", tenant_id=tenant_id)
        repo = FakeRoleRepo([role])
        service = RoleManagementService(repo)

        with pytest.raises(ValidationError, match="already exists"):
            await service.create_custom_role(
                tenant_id, RoleCreateRequest(name="ops", permission_keys=["users:read"])
            )

    async def test_rejects_unknown_permissions(self) -> None:
        service = RoleManagementService(FakeRoleRepo())

        with pytest.raises(ValidationError, match="Unknown permission"):
            await service.create_custom_role(
                uuid.uuid4(), RoleCreateRequest(name="ops", permission_keys=["nope:wat"])
            )

    async def test_creates_custom_role(self) -> None:
        repo = FakeRoleRepo()
        service = RoleManagementService(repo)

        role = await service.create_custom_role(
            uuid.uuid4(), RoleCreateRequest(name="ops", permission_keys=["roles:read"])
        )

        assert role.name == "ops"
        assert role.is_system_role is False
        assert role.permissions == ["roles:read"]


class TestUpdateRole:
    async def test_updates_name_and_permissions(self) -> None:
        tenant_id = uuid.uuid4()
        role = _make_role(name="ops", permissions=["roles:read"], tenant_id=tenant_id)
        repo = FakeRoleRepo([role])
        service = RoleManagementService(repo)

        updated = await service.update_role(
            tenant_id, role.id, name="super_ops", permissions=["roles:write"]
        )

        assert updated.name == "super_ops"
        assert updated.permissions == ["roles:write"]

    async def test_rejects_unknown_permissions(self) -> None:
        tenant_id = uuid.uuid4()
        role = _make_role(name="ops", tenant_id=tenant_id)
        repo = FakeRoleRepo([role])
        service = RoleManagementService(repo)

        with pytest.raises(ValidationError, match="Unknown permission"):
            await service.update_role(tenant_id, role.id, permissions=["nope:wat"])

    async def test_rejects_reserved_system_name(self) -> None:
        tenant_id = uuid.uuid4()
        role = _make_role(name="ops", tenant_id=tenant_id)
        repo = FakeRoleRepo([role])
        service = RoleManagementService(repo)

        with pytest.raises(ValidationError, match="reserved system role"):
            await service.update_role(tenant_id, role.id, name="tenant_owner")

    async def test_rejects_cross_tenant_role(self) -> None:
        other_tenant_id = uuid.uuid4()
        role = _make_role(name="ops", tenant_id=other_tenant_id)
        repo = FakeRoleRepo([role])
        service = RoleManagementService(repo)

        with pytest.raises(NotFoundError):
            await service.update_role(uuid.uuid4(), role.id, name="newname")

    async def test_rejects_nothing_to_update(self) -> None:
        tenant_id = uuid.uuid4()
        role = _make_role(name="ops", tenant_id=tenant_id)
        repo = FakeRoleRepo([role])
        service = RoleManagementService(repo)

        with pytest.raises(ValidationError, match="Nothing to update"):
            await service.update_role(tenant_id, role.id)


class TestDeleteRole:
    async def test_deletes_custom_role(self) -> None:
        tenant_id = uuid.uuid4()
        role = _make_role(name="ops", tenant_id=tenant_id)
        repo = FakeRoleRepo([role])
        service = RoleManagementService(repo)

        await service.delete_role(tenant_id, role.id)

        assert role.id in repo.deleted
        assert await repo.get_by_id(role.id) is None

    async def test_rejects_system_role_deletion(self) -> None:
        tenant_id = uuid.uuid4()
        role = _make_role(name="auditor", tenant_id=tenant_id, is_system_role=True)
        repo = FakeRoleRepo([role])
        service = RoleManagementService(repo)

        with pytest.raises(ValidationError, match="System roles cannot be deleted"):
            await service.delete_role(tenant_id, role.id)

        assert repo.deleted == []

    async def test_rejects_cross_tenant_role(self) -> None:
        other_tenant_id = uuid.uuid4()
        role = _make_role(name="ops", tenant_id=other_tenant_id)
        repo = FakeRoleRepo([role])
        service = RoleManagementService(repo)

        with pytest.raises(NotFoundError):
            await service.delete_role(uuid.uuid4(), role.id)


class TestAssignRole:
    async def test_assigns_role_at_tenant_scope(self) -> None:
        tenant_id = uuid.uuid4()
        role = _make_role(name="ops", tenant_id=tenant_id)
        repo = FakeRoleRepo([role])
        service = RoleManagementService(repo)

        await service.assign_role(tenant_id, role.id, user_id=uuid.uuid4())

        assert len(repo.grants) == 1
        grant = repo.grants[0]
        assert grant["scope_type"] == ScopeType.TENANT
        assert grant["scope_id"] == uuid.UUID(str(tenant_id))

    async def test_assigns_role_at_specific_scope(self) -> None:
        tenant_id = uuid.uuid4()
        team_id = uuid.uuid4()
        role = _make_role(name="ops", tenant_id=tenant_id)
        repo = FakeRoleRepo([role])
        service = RoleManagementService(repo)

        await service.assign_role(
            tenant_id,
            role.id,
            user_id=uuid.uuid4(),
            scope_type=ScopeType.TEAM,
            scope_id=team_id,
        )

        assert len(repo.grants) == 1
        grant = repo.grants[0]
        assert grant["scope_type"] == ScopeType.TEAM
        assert grant["scope_id"] == team_id

    async def test_requires_scope_id_for_non_tenant_scope(self) -> None:
        tenant_id = uuid.uuid4()
        role = _make_role(name="ops", tenant_id=tenant_id)
        repo = FakeRoleRepo([role])
        service = RoleManagementService(repo)

        with pytest.raises(ValidationError, match="scope_id is required"):
            await service.assign_role(
                tenant_id, role.id, user_id=uuid.uuid4(), scope_type=ScopeType.TEAM
            )

    async def test_duplicate_assign_is_idempotent(self) -> None:
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        role = _make_role(name="ops", tenant_id=tenant_id)
        repo = FakeRoleRepo([role])
        service = RoleManagementService(repo)

        await service.assign_role(tenant_id, role.id, user_id=user_id)
        await service.assign_role(tenant_id, role.id, user_id=user_id)

        assert len(repo.grants) == 1

    async def test_rejects_cross_tenant_role(self) -> None:
        other_tenant_id = uuid.uuid4()
        role = _make_role(name="ops", tenant_id=other_tenant_id)
        repo = FakeRoleRepo([role])
        service = RoleManagementService(repo)

        with pytest.raises(NotFoundError):
            await service.assign_role(uuid.uuid4(), role.id, user_id=uuid.uuid4())
