"""bridgeon-solutions seed regression: re-seed idempotency, rotation, Entry C repair.

SEC-CLEAN-001 regression for the seed path that previously produced a tenant
with users but no RBAC rows (symptom: "No spaces available yet."). Proves the
atomic, credential-converging seeder end to end:

- a full seed, then a re-seed, leaves the RBAC row sets (roles /
  memberships / user_roles) identical - nothing dropped, nothing duplicated,
  IDs survive;
- rotating credentials re-applies password hashes and the MFA secret while
  the RBAC row sets survive untouched;
- a tenant deliberately degraded to Entry C's shape (tenant + users present,
  all RBAC rows deleted) is fully repaired by a single re-seed, without
  duplicating users.

Uses generated credentials passed to :func:`seed_bridgeon` directly - the
gitignored ``.env`` values are never read here.

Hermetic by design: if the ``bridgeon-solutions`` tenant already exists on
this database (a live dev/E2E DB), the tests SKIP rather than touch the real
demo tenant. CI runs against a fresh Postgres where the tenant is absent, so
the guard only fires on developer machines.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete, func, select

from identity.core.constants import SYSTEM_ROLE_DEFINITIONS
from identity.core.security import decrypt_mfa_secret, verify_password
from identity.db.session import async_session_factory
from identity.domain.entities import MembershipStatus, ScopeType
from identity.features.memberships.repository import MembershipRepository
from identity.features.roles.repository import RoleRepository
from identity.features.users.repository import UserRepository
from identity.models import (
    MembershipModel,
    RoleModel,
    TenantModel,
    UserModel,
    UserRoleModel,
)
from identity.seed_bridgeon import (
    BRIDGEON_SLUG,
    BRIDGEON_TENANT_ID,
    BRIDGEON_USERS,
    seed_bridgeon,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# Generated test credentials - never the gitignored .env values.
_OWNER_PW_V1 = "Owner#Bridgeon2026a"
_OWNER_PW_V2 = "Owner#Bridgeon2027b"
_ADMIN_PW_V1 = "Admin#Bridgeon2026a"
_ADMIN_PW_V2 = "Admin#Bridgeon2027b"
_TEAM_PW_V1 = "Team#Bridgeon2026a"
_TEAM_PW_V2 = "Team#Bridgeon2027b"
_TOTP_V1 = "AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHH"
_TOTP_V2 = "HHHHGGGGFFFFEEEEDDDDCCCCBBBBAAAA"


def _rotated_password(role_name: str) -> str:
    """Post-rotation password for a role: owner/admin keep their own, staff share."""
    if role_name == "tenant_owner":
        return _OWNER_PW_V2
    if role_name == "organization_admin":
        return _ADMIN_PW_V2
    return _TEAM_PW_V2


async def _ensure_hermetic() -> None:
    """Skip when a real bridgeon-solutions tenant already exists."""
    async with async_session_factory() as session:
        exists = (
            await session.scalar(select(TenantModel.id).where(TenantModel.slug == BRIDGEON_SLUG))
        ) is not None
    if exists:
        pytest.skip(
            "bridgeon-solutions tenant already present - refusing to run the "
            "regression seed against live data"
        )


async def _rbac_counts(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, model in (
        ("roles", RoleModel),
        ("memberships", MembershipModel),
        ("user_roles", UserRoleModel),
        ("users", UserModel),
    ):
        counts[name] = (
            await session.execute(
                select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
            )
        ).scalar_one()
    return counts


async def _rbac_ids(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, list[uuid.UUID]]:
    ids: dict[str, list[uuid.UUID]] = {}
    for name, model in (
        ("role_ids", RoleModel),
        ("membership_ids", MembershipModel),
        ("user_role_ids", UserRoleModel),
        ("user_ids", UserModel),
    ):
        rows = await session.execute(
            select(model.id).where(model.tenant_id == tenant_id).order_by(model.id)
        )
        ids[name] = list(rows.scalars())
    return ids


async def _cleanup(tenant_id: uuid.UUID) -> None:
    """Remove every row the seed created for the tenant, in FK order."""
    async with async_session_factory() as session:
        await session.execute(delete(UserRoleModel).where(UserRoleModel.tenant_id == tenant_id))
        await session.execute(delete(MembershipModel).where(MembershipModel.tenant_id == tenant_id))
        await session.execute(delete(UserModel).where(UserModel.tenant_id == tenant_id))
        await session.execute(delete(RoleModel).where(RoleModel.tenant_id == tenant_id))
        await session.execute(delete(TenantModel).where(TenantModel.id == tenant_id))
        await session.commit()


async def _assert_accounts_ready(tenant_id: uuid.UUID) -> None:
    """Every BRIDGEON_USERS account must resolve: user + active membership +
    tenant-scoped grant on its named role."""
    async with async_session_factory() as session:
        user_repo = UserRepository(session)
        membership_repo = MembershipRepository(session)
        role_repo = RoleRepository(session)

        for email, _full_name, role_name in BRIDGEON_USERS:
            user = await user_repo.get_by_email(tenant_id, email)
            assert user is not None and user.id is not None, f"{email} must be seeded"
            assert user.is_active is True
            assert user.is_verified is True

            role = await role_repo.get_by_name(tenant_id, role_name)
            assert role is not None and role.id is not None, f"{role_name} role must exist"

            membership = await membership_repo.get_by_user(user.id, tenant_id)
            assert membership is not None, f"{email} must hold a membership"
            assert membership.status == MembershipStatus.ACTIVE
            assert membership.role_id == role.id

            granted = await role_repo.grant_exists(user.id, role.id, ScopeType.TENANT, tenant_id)
            assert granted is True, f"{email} must hold the tenant-scoped {role_name} grant"


async def test_reseed_preserves_rbac_row_set(migrated_schema: None) -> None:
    """Seed twice: the second run must be a no-op on RBAC row sets + IDs."""
    await _ensure_hermetic()
    tenant_id = uuid.UUID(BRIDGEON_TENANT_ID)
    try:
        await seed_bridgeon(
            owner_password=_OWNER_PW_V1,
            org_admin_password=_ADMIN_PW_V1,
            team_password=_TEAM_PW_V1,
            mfa_secret=_TOTP_V1,
        )
        async with async_session_factory() as session:
            counts_first = await _rbac_counts(session, tenant_id)
            ids_first = await _rbac_ids(session, tenant_id)

        await seed_bridgeon(
            owner_password=_OWNER_PW_V1,
            org_admin_password=_ADMIN_PW_V1,
            team_password=_TEAM_PW_V1,
            mfa_secret=_TOTP_V1,
        )
        async with async_session_factory() as session:
            counts_second = await _rbac_counts(session, tenant_id)
            ids_second = await _rbac_ids(session, tenant_id)

        assert counts_first == counts_second, (
            "re-seed changed the RBAC row set - Entry C regression",
            counts_first,
            counts_second,
        )
        assert ids_first == ids_second, "re-seed changed row ids - nothing may be recreated"

        await _assert_accounts_ready(tenant_id)
    finally:
        await _cleanup(tenant_id)


async def test_rotation_updates_credentials_keeps_rbac(migrated_schema: None) -> None:
    """Rotating credentials must re-apply hashes + MFA secret and preserve RBAC."""
    await _ensure_hermetic()
    tenant_id = uuid.UUID(BRIDGEON_TENANT_ID)
    try:
        await seed_bridgeon(
            owner_password=_OWNER_PW_V1,
            org_admin_password=_ADMIN_PW_V1,
            team_password=_TEAM_PW_V1,
            mfa_secret=_TOTP_V1,
        )
        async with async_session_factory() as session:
            ids_before = await _rbac_ids(session, tenant_id)

        await seed_bridgeon(
            owner_password=_OWNER_PW_V2,
            org_admin_password=_ADMIN_PW_V2,
            team_password=_TEAM_PW_V2,
            mfa_secret=_TOTP_V2,
        )
        async with async_session_factory() as session:
            ids_after = await _rbac_ids(session, tenant_id)
            assert ids_after == ids_before, "rotation must not touch RBAC rows"

            user_repo = UserRepository(session)
            for email, _full_name, role_name in BRIDGEON_USERS:
                user = await user_repo.get_by_email(tenant_id, email)
                assert user is not None and user.password_hash is not None

                new_password = _rotated_password(role_name)
                assert verify_password(new_password, user.password_hash), (
                    f"rotated password must verify for {email}"
                )
                assert user.mfa_secret is not None, f"MFA secret must be set for {email}"
                assert decrypt_mfa_secret(user.mfa_secret) == _TOTP_V2, (
                    f"rotated MFA secret must be applied for {email}"
                )

        await _assert_accounts_ready(tenant_id)
    finally:
        await _cleanup(tenant_id)


async def test_reseed_repairs_degrated_rbac_shape(migrated_schema: None) -> None:
    """Entry C healing: users present + RBAC rows deleted -> one re-seed fixes all."""
    await _ensure_hermetic()
    tenant_id = uuid.UUID(BRIDGEON_TENANT_ID)
    try:
        await seed_bridgeon(
            owner_password=_OWNER_PW_V1,
            org_admin_password=_ADMIN_PW_V1,
            team_password=_TEAM_PW_V1,
            mfa_secret=_TOTP_V1,
        )

        # Degrade to the Entry C shape: strip all RBAC rows, keep tenant+users.
        async with async_session_factory() as session:
            user_ids_before = (await _rbac_ids(session, tenant_id))["user_ids"]
            await session.execute(delete(UserRoleModel).where(UserRoleModel.tenant_id == tenant_id))
            await session.execute(
                delete(MembershipModel).where(MembershipModel.tenant_id == tenant_id)
            )
            await session.execute(delete(RoleModel).where(RoleModel.tenant_id == tenant_id))
            await session.commit()

        await seed_bridgeon(
            owner_password=_OWNER_PW_V1,
            org_admin_password=_ADMIN_PW_V1,
            team_password=_TEAM_PW_V1,
            mfa_secret=_TOTP_V1,
        )

        async with async_session_factory() as session:
            counts = await _rbac_counts(session, tenant_id)
            ids = await _rbac_ids(session, tenant_id)

        assert counts["roles"] == len(SYSTEM_ROLE_DEFINITIONS)
        assert counts["memberships"] == len(BRIDGEON_USERS)
        assert counts["user_roles"] == len(BRIDGEON_USERS)
        assert counts["users"] == len(BRIDGEON_USERS)
        assert ids["user_ids"] == user_ids_before, (
            "repair must converge the existing users, not duplicate them"
        )

        await _assert_accounts_ready(tenant_id)
    finally:
        await _cleanup(tenant_id)
