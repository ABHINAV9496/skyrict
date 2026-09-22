"""Database seeding - bootstrap default tenants, roles, and admin users.

Usage:
    python -m identity.seed
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from identity.core.config import settings
from identity.core.constants import SYSTEM_ROLE_DEFINITIONS
from identity.core.security import hash_password
from identity.db.session import async_session_factory
from identity.domain.entities import (
    Membership,
    MembershipStatus,
    Role,
    ScopeType,
    Tenant,
    User,
)
from identity.features.memberships.repository import MembershipRepository
from identity.features.roles.repository import RoleRepository

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("identity.seed")

DEFAULT_ROLES: list[tuple[str, list[str]]] = [
    (name, list(permissions)) for name, permissions in SYSTEM_ROLE_DEFINITIONS
]

# RBAC E2E coverage (SKY-104): a non-owner account that can read finance and
# reports but has deliberately NO erp.payroll.* permission. Core mirrors the
# role + grant on boot (core.api.lifespan -> sync_rbac_from_identity), so the
# E2E suite can drive real 403-style denial through the request-time
# require_permission path.
FINANCE_VIEWER_ROLE = "finance_viewer"
FINANCE_VIEWER_EMAIL = "finance@skyrict.io"
FINANCE_VIEWER_PASSWORD = "Finance123!"
FINANCE_VIEWER_PERMISSIONS = tuple(
    {
        "users:read",
        "settings:read",
        "erp.invoice.read",
        "erp.crm.read",
        "erp.sales.read",
        "erp.inventory.read",
        "erp.finance.read",
        "erp.hr.read",
        "erp.reports.read",
    }
)


@asynccontextmanager
async def _transaction(session: AsyncSession | None) -> AsyncIterator[AsyncSession]:
    """Share the caller's session, or open + commit one when none is given.

    Passing a ``session`` (the :func:`run_seed` path) makes every seed step run
    inside ONE atomic transaction: no step commits on its own, :func:`run_seed`
    commits once at the end, and any failure rolls the whole seed back - a
    tenant can never be committed with users but no RBAC rows (SEC-CLEAN-001).

    Standalone calls (tests, scripts) get their own session and an immediate
    commit on success - rolled back on error.
    """
    if session is not None:
        yield session
        return
    async with async_session_factory() as own:
        yield own
        await own.commit()


async def seed_default_tenant(session: AsyncSession | None = None) -> None:
    """Create the default tenant if it doesn't exist."""
    from identity.features.organizations.repository import TenantRepository

    async with _transaction(session) as s:
        repo = TenantRepository(s)
        existing = await repo.get_by_slug("default")
        if existing:
            logger.info("seed.tenant.exists", slug="default")
            return

        tenant = Tenant(
            name="Default Organization",
            slug="default",
            is_active=True,
            plan_tier="free",
            id=uuid.UUID(settings.DEFAULT_TENANT_ID),
        )
        await repo.create(tenant)
        logger.info("seed.tenant.created", slug="default", id=str(tenant.id))


async def seed_default_roles(session: AsyncSession | None = None) -> None:
    """Create the default tenant's missing system roles.

    Per-name: a tenant with a partial role set gets the missing roles added
    instead of being skipped wholesale (a pre-existing idempotency bug that
    left tenants with 1-5 of 6 system roles after a partial seed).
    """
    default_tenant_id = uuid.UUID(settings.DEFAULT_TENANT_ID)

    async with _transaction(session) as s:
        repo = RoleRepository(s)
        missing: list[tuple[str, list[str]]] = []
        for name, permissions in DEFAULT_ROLES:
            role = await repo.get_by_name(default_tenant_id, name)
            if role is None:
                missing.append((name, permissions))

        if not missing:
            logger.info("seed.roles.exists", count=len(DEFAULT_ROLES))
            return

        for name, permissions in missing:
            await repo.create(
                Role(
                    tenant_id=default_tenant_id,
                    name=name,
                    permissions=permissions,
                    is_system_role=True,
                )
            )
        logger.info("seed.roles.created", count=len(missing))


async def seed_admin_user(session: AsyncSession | None = None) -> None:
    """Create a default admin user for development/staging."""
    from identity.features.users.repository import UserRepository

    default_tenant_id = uuid.UUID(settings.DEFAULT_TENANT_ID)

    async with _transaction(session) as s:
        repo = UserRepository(s)
        existing = await repo.get_by_email(default_tenant_id, "admin@skyrict.io")
        if existing:
            logger.info("seed.admin.exists")
            return

        user = User(
            tenant_id=default_tenant_id,
            email="admin@skyrict.io",
            password_hash=hash_password("Admin123!"),
            full_name="System Admin",
            is_active=True,
            is_verified=True,
        )
        await repo.create(user)
        logger.info("seed.admin.created", email="admin@skyrict.io")


async def seed_admin_membership(session: AsyncSession | None = None) -> None:
    """Grant the seeded admin the tenant_owner role + an active membership.

    The admin user alone is not enough: membership scopes RBAC reads and the
    role carries the wildcard ``*`` permission (plus ``invitations:send``)
    that the members dashboard needs. Idempotent - safe to re-run.

    Raises when the user/role is missing instead of silently skipping, so a
    degraded default tenant fails loudly - and inside :func:`run_seed` this
    aborts and rolls back the whole seed (SEC-CLEAN-001).
    """
    from identity.features.users.repository import UserRepository

    default_tenant_id = uuid.UUID(settings.DEFAULT_TENANT_ID)

    async with _transaction(session) as s:
        user_repo = UserRepository(s)
        role_repo = RoleRepository(s)
        membership_repo = MembershipRepository(s)

        user = await user_repo.get_by_email(default_tenant_id, "admin@skyrict.io")
        if user is None or user.id is None:
            raise RuntimeError(
                "seed_admin_membership: admin@skyrict.io user missing; "
                "refusing to grant RBAC to a nonexistent account"
            )

        owner_role = await role_repo.get_by_name(default_tenant_id, "tenant_owner")
        if owner_role is None or owner_role.id is None:
            raise RuntimeError(
                "seed_admin_membership: tenant_owner role missing; "
                "refusing to grant a role that does not exist"
            )

        existing = await membership_repo.get_by_user(user.id, default_tenant_id)
        if existing is None:
            await membership_repo.create(
                Membership(
                    tenant_id=default_tenant_id,
                    user_id=user.id,
                    invited_email=user.email,
                    status=MembershipStatus.ACTIVE,
                    role_id=owner_role.id,
                    joined_at=datetime.now(UTC),
                )
            )
            logger.info("seed.admin_membership.created", email=user.email)

        granted = await role_repo.grant_exists(
            user.id, owner_role.id, ScopeType.TENANT, default_tenant_id
        )
        if not granted:
            await role_repo.grant_to_user(
                user_id=user.id,
                role_id=owner_role.id,
                tenant_id=default_tenant_id,
                scope_id=default_tenant_id,
            )
            logger.info("seed.admin_membership.granted", role="tenant_owner", email=user.email)


async def seed_finance_viewer(session: AsyncSession | None = None) -> None:
    """Seed the finance_viewer role + user for RBAC E2E coverage.

    Mirrors ``seed_admin_membership``: creates the custom ``finance_viewer``
    role (standard-user read permissions plus ``erp.reports.read``, with no
    ``erp.payroll.*`` keys), the ``finance@skyrict.io`` user, an active
    membership, and the tenant-scoped role grant on the default tenant.
    Idempotent - safe to re-run, and the E2E stack re-seeds on every boot.

    Core's lifespan sync (``core.api.lifespan`` ->
    ``sync_rbac_from_identity``) copies identity roles/grants into
    ``core_roles``/``core_user_roles`` when the core API boots, so this user
    resolves through the real request-time ``require_permission`` path: finance
    read endpoints stay open while payroll endpoints deny with 403.
    """
    from identity.features.users.repository import UserRepository

    default_tenant_id = uuid.UUID(settings.DEFAULT_TENANT_ID)

    async with _transaction(session) as s:
        user_repo = UserRepository(s)
        role_repo = RoleRepository(s)
        membership_repo = MembershipRepository(s)

        role = await role_repo.get_by_name(default_tenant_id, FINANCE_VIEWER_ROLE)
        if role is None:
            role = await role_repo.create(
                Role(
                    tenant_id=default_tenant_id,
                    name=FINANCE_VIEWER_ROLE,
                    permissions=list(FINANCE_VIEWER_PERMISSIONS),
                    is_system_role=False,
                )
            )
            logger.info("seed.finance_viewer.role.created", role=FINANCE_VIEWER_ROLE)
        if role.id is None:
            raise RuntimeError(f"seeded {FINANCE_VIEWER_ROLE} role has no id")

        user = await user_repo.get_by_email(default_tenant_id, FINANCE_VIEWER_EMAIL)
        if user is None:
            user = await user_repo.create(
                User(
                    tenant_id=default_tenant_id,
                    email=FINANCE_VIEWER_EMAIL,
                    password_hash=hash_password(FINANCE_VIEWER_PASSWORD),
                    full_name="Finance Viewer",
                    is_active=True,
                    is_verified=True,
                )
            )
            logger.info("seed.finance_viewer.user.created", email=FINANCE_VIEWER_EMAIL)
        if user.id is None:
            raise RuntimeError(f"seeded user {FINANCE_VIEWER_EMAIL} has no id")

        membership = await membership_repo.get_by_user(user.id, default_tenant_id)
        if membership is None:
            await membership_repo.create(
                Membership(
                    tenant_id=default_tenant_id,
                    user_id=user.id,
                    invited_email=user.email,
                    status=MembershipStatus.ACTIVE,
                    role_id=role.id,
                    joined_at=datetime.now(UTC),
                )
            )
            logger.info("seed.finance_viewer.membership.created", email=user.email)

        granted = await role_repo.grant_exists(
            user.id, role.id, ScopeType.TENANT, default_tenant_id
        )
        if not granted:
            await role_repo.grant_to_user(
                user_id=user.id,
                role_id=role.id,
                tenant_id=default_tenant_id,
                scope_id=default_tenant_id,
            )
            logger.info("seed.finance_viewer.granted", role=FINANCE_VIEWER_ROLE, email=user.email)


async def run_seed() -> None:
    """Run all seed operations as ONE atomic transaction.

    Every step shares a single session and nothing commits until the end, so
    a failure mid-seed rolls back the whole run - users, roles, memberships
    and grants are committed together or not at all (SEC-CLEAN-001).
    """
    logger.info("seed.start")
    async with async_session_factory() as session:
        await seed_default_tenant(session)
        await seed_default_roles(session)
        await seed_admin_user(session)
        await seed_admin_membership(session)
        await seed_finance_viewer(session)
        await session.commit()
    logger.info("seed.complete")


if __name__ == "__main__":
    asyncio.run(run_seed())
