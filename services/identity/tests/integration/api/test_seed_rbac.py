"""Seed finance_viewer role + grant idempotency (RBAC E2E coverage, SKY-104).

Runs against the migrated schema; skipped locally when Postgres is
unreachable (see tests/integration/api/conftest.py). Verifies the E2E RBAC
fixture the auth suite relies on:

- the custom ``finance_viewer`` role exists with finance/reports read
  permissions and NO ``erp.payroll.*`` key;
- the ``finance@skyrict.io`` user exists with an ACTIVE membership and a
  tenant-scoped grant;
- a second seed run is a no-op (idempotent).

Core's lifespan sync mirrors identity roles/grants into
``core_roles``/``core_user_roles`` at boot, so this fixture resolves through
the real request-time ``require_permission`` path in the full stack - finance
read stays open while payroll denies with 403.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from identity.core.config import settings
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
from identity.seed import (
    FINANCE_VIEWER_EMAIL,
    FINANCE_VIEWER_PERMISSIONS,
    FINANCE_VIEWER_ROLE,
    seed_default_tenant,
    seed_finance_viewer,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]


async def test_seed_finance_viewer_idempotent(migrated_schema: None) -> None:
    default_tenant_id = uuid.UUID(settings.DEFAULT_TENANT_ID)

    async with async_session_factory() as session:
        tenant_exists = (
            await session.scalar(select(TenantModel.id).where(TenantModel.id == default_tenant_id))
        ) is not None

    created_role_id: uuid.UUID | None = None
    created_user_id: uuid.UUID | None = None

    try:
        # The integration DB is seeded with its own tenants (olympus/globex);
        # the default tenant is created here when absent. seed_default_tenant
        # is idempotent, mirroring how `python -m identity.seed` runs it first.
        await seed_default_tenant()
        await seed_finance_viewer()
        await seed_finance_viewer()  # second run must be a no-op

        async with async_session_factory() as session:
            role_repo = RoleRepository(session)
            user_repo = UserRepository(session)
            membership_repo = MembershipRepository(session)

            role = await role_repo.get_by_name(default_tenant_id, FINANCE_VIEWER_ROLE)
            assert role is not None, "finance_viewer role must be seeded"
            assert role.id is not None, "finance_viewer role must have an id"
            assert role.is_system_role is False, "finance_viewer is a custom role"
            assert set(role.permissions) == set(FINANCE_VIEWER_PERMISSIONS)
            assert not any(
                permission.startswith("erp.payroll.") for permission in role.permissions
            ), "finance_viewer must never carry payroll permissions"

            user = await user_repo.get_by_email(default_tenant_id, FINANCE_VIEWER_EMAIL)
            assert user is not None and user.id is not None, "finance user must be seeded"
            assert user.is_active is True
            assert user.is_verified is True

            membership = await membership_repo.get_by_user(user.id, default_tenant_id)
            assert membership is not None, "finance user must hold an active membership"
            assert membership.status == MembershipStatus.ACTIVE
            assert membership.role_id == role.id

            granted = await role_repo.grant_exists(
                user.id, role.id, ScopeType.TENANT, default_tenant_id
            )
            assert granted is True, "finance user must hold the tenant-scoped grant"

            created_role_id = role.id
            created_user_id = user.id
    finally:
        # Remove only the rows this test created, in FK order. The default
        # tenant is deleted only when this test created it.
        async with async_session_factory() as session:
            if created_user_id is not None:
                await session.execute(
                    delete(UserRoleModel).where(UserRoleModel.user_id == created_user_id)
                )
                await session.execute(
                    delete(MembershipModel).where(MembershipModel.user_id == created_user_id)
                )
                await session.execute(delete(UserModel).where(UserModel.id == created_user_id))
            if created_role_id is not None:
                await session.execute(delete(RoleModel).where(RoleModel.id == created_role_id))
            if not tenant_exists:
                await session.execute(
                    delete(TenantModel).where(TenantModel.id == default_tenant_id)
                )
            await session.commit()
