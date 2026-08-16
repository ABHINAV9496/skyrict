"""Database seeding — bootstrap default tenants, roles, and admin users.

Usage:
    python -m identity.seed
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog

from identity.core.config import settings
from identity.core.constants import SYSTEM_ROLE_DEFINITIONS
from identity.core.security import hash_password
from identity.db.session import async_session_factory
from identity.domain.entities import Membership, MembershipStatus, ScopeType, Tenant, User
from identity.features.memberships.repository import MembershipRepository
from identity.features.roles.repository import RoleRepository
from identity.models.role import RoleModel

logger = structlog.get_logger("identity.seed")

DEFAULT_ROLES = [
    {"name": name, "permissions": list(permissions)}
    for name, permissions in SYSTEM_ROLE_DEFINITIONS
]


async def seed_default_tenant() -> None:
    """Create the default tenant if it doesn't exist."""
    from identity.features.organizations.repository import TenantRepository

    async with async_session_factory() as session:
        repo = TenantRepository(session)
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
        await repo.commit()
        logger.info("seed.tenant.created", slug="default", id=str(tenant.id))


async def seed_default_roles() -> None:
    """Create default RBAC roles for the default tenant."""
    from identity.db.repository import BaseRepository

    async with async_session_factory() as session:
        repo = BaseRepository[RoleModel](session, model=RoleModel)

        existing = await repo.list(
            filters=[RoleModel.tenant_id == uuid.UUID(settings.DEFAULT_TENANT_ID)]
        )
        if existing:
            logger.info("seed.roles.exists", count=len(existing))
            return

        for role_data in DEFAULT_ROLES:
            role = RoleModel(
                tenant_id=uuid.UUID(settings.DEFAULT_TENANT_ID),
                name=role_data["name"],
                permissions=role_data["permissions"],
                is_system_role=True,
            )
            await repo.create(role)

        await repo.commit()
        logger.info("seed.roles.created", count=len(DEFAULT_ROLES))


async def seed_admin_user() -> None:
    """Create a default admin user for development/staging."""
    from identity.features.users.repository import UserRepository

    default_tenant_id = uuid.UUID(settings.DEFAULT_TENANT_ID)

    async with async_session_factory() as session:
        repo = UserRepository(session)
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
        await repo.commit()
        logger.info("seed.admin.created", email="admin@skyrict.io")


async def seed_admin_membership() -> None:
    """Grant the seeded admin the tenant_owner role + an active membership.

    The admin user alone is not enough: membership scopes RBAC reads and the
    role carries the wildcard ``*`` permission (plus ``invitations:send``)
    that the members dashboard needs. Idempotent — safe to re-run.
    """
    from identity.features.users.repository import UserRepository

    default_tenant_id = uuid.UUID(settings.DEFAULT_TENANT_ID)

    async with async_session_factory() as session:
        user_repo = UserRepository(session)
        role_repo = RoleRepository(session)
        membership_repo = MembershipRepository(session)

        user = await user_repo.get_by_email(default_tenant_id, "admin@skyrict.io")
        if user is None or user.id is None:
            logger.warning("seed.admin_membership.user_missing")
            return

        owner_role = await role_repo.get_by_name(default_tenant_id, "tenant_owner")
        if owner_role is None or owner_role.id is None:
            logger.warning("seed.admin_membership.role_missing")
            return

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

        await session.commit()


async def run_seed() -> None:
    """Run all seed operations."""
    logger.info("seed.start")
    await seed_default_tenant()
    await seed_default_roles()
    await seed_admin_user()
    await seed_admin_membership()
    logger.info("seed.complete")


if __name__ == "__main__":
    asyncio.run(run_seed())
