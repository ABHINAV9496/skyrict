"""Seed the ``bridgeon-solutions`` demo tenant (identity side).

Reusable, idempotent provisioning for the ``bridgeon-solutions`` demo
workspace used by the HR/Payroll/Finance walkthrough gates. The E2E compose
stack only seeds the ``default`` tenant; this module restores the demo
tenant that previously lived in the ad-hoc dev database.

What it creates (all scoped to the ``bridgeon-solutions`` tenant):

- the tenant itself (fixed slug ``bridgeon-solutions``, fixed UUID
  ``00000000-0000-0000-0000-000000000002``),
- the six ``SYSTEM_ROLE_DEFINITIONS`` roles,
- ``abhikrishna616@gmail.com`` (``tenant_owner``) and
  ``admin@bridgeon.io`` (``organization_admin``),
- an active membership + tenant-scoped role grant for each user.

Idempotent - safe to re-run; a tenant that already exists is left alone.

Dev credentials documented here are shared dev secrets only:

- ``abhikrishna616@gmail.com`` / ``Abhikrishna61@``  (tenant_owner)
- ``admin@bridgeon.io``        / ``BridgeonAdmin1!`` (organization_admin)

MFA is seeded **enrolled** on both accounts with the fixed dev TOTP secret
``JBSWY3DPEHPK3PXP`` (RFC 6238 test vector, base32). This mirrors the
documented dev state in ``docs/runbooks/dev-environment-known-issues.md``
Entry A (a known secret so the headless gate logins can pass the mandatory
MFA challenge). Treat the secret and passwords as shared dev secrets; rotate
all of them before any real use of the tenant.

Usage:
    python -m identity.seed_bridgeon
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog

from identity.core.constants import SYSTEM_ROLE_DEFINITIONS
from identity.core.security import encrypt_mfa_secret, hash_password
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
from identity.features.organizations.repository import TenantRepository
from identity.features.roles.repository import RoleRepository
from identity.features.users.repository import UserRepository

logger = structlog.get_logger("identity.seed.bridgeon")

BRIDGEON_TENANT_ID = "00000000-0000-0000-0000-000000000002"
BRIDGEON_SLUG = "bridgeon-solutions"
BRIDGEON_NAME = "Bridgeon Solutions"

# Fixed dev TOTP secret so the seed is repeatable and headless gate logins
# can generate the challenge code (RFC 6238 test vector, base32).
BRIDGEON_MFA_SECRET = "JBSWY3DPEHPK3PXP"

# (email, full_name, password, role_name)
BRIDGEON_USERS: tuple[tuple[str, str, str, str], ...] = (
    (
        "abhikrishna616@gmail.com",
        "Abhikrishna",
        "Abhikrishna61@",
        "tenant_owner",
    ),
    (
        "admin@bridgeon.io",
        "Bridgeon Admin",
        "BridgeonAdmin1!",
        "organization_admin",
    ),
)


async def seed_bridgeon_tenant() -> uuid.UUID:
    """Create the bridgeon-solutions tenant if absent; return its id."""
    tenant_id = uuid.UUID(BRIDGEON_TENANT_ID)
    async with async_session_factory() as session:
        repo = TenantRepository(session)
        existing = await repo.get_by_slug(BRIDGEON_SLUG)
        if existing is not None and existing.id is not None:
            logger.info("seed.bridgeon.tenant.exists", slug=BRIDGEON_SLUG, id=str(existing.id))
            return existing.id

        tenant = Tenant(
            name=BRIDGEON_NAME,
            slug=BRIDGEON_SLUG,
            is_active=True,
            plan_tier="free",
            id=tenant_id,
        )
        await repo.create(tenant)
        await repo.commit()
        logger.info("seed.bridgeon.tenant.created", slug=BRIDGEON_SLUG, id=str(tenant_id))
        return tenant_id


async def seed_bridgeon_roles(tenant_id: uuid.UUID) -> dict[str, Role]:
    """Create the system roles for the tenant; return a name -> role map."""
    async with async_session_factory() as session:
        repo = RoleRepository(session)
        existing = {
            role.name: role
            for role in await repo.list_by_tenant(tenant_id, limit=100)
            if role.name is not None
        }
        created: dict[str, Role] = {}
        for name, permissions in SYSTEM_ROLE_DEFINITIONS:
            if name in existing:
                continue
            role = await repo.create(
                Role(
                    tenant_id=tenant_id,
                    name=name,
                    permissions=list(permissions),
                    is_system_role=True,
                )
            )
            created[name] = role
            logger.info("seed.bridgeon.role.created", role=name, tenant_id=str(tenant_id))
        await session.commit()
        return {**existing, **created}


async def seed_bridgeon_users(
    tenant_id: uuid.UUID,
    roles_by_name: dict[str, Role],
) -> None:
    """Create users, active memberships, and tenant-scoped grants."""
    async with async_session_factory() as session:
        user_repo = UserRepository(session)
        membership_repo = MembershipRepository(session)
        role_repo = RoleRepository(session)

        for email, full_name, password, role_name in BRIDGEON_USERS:
            role = roles_by_name.get(role_name)
            if role is None or role.id is None:
                logger.warning(
                    "seed.bridgeon.role.missing",
                    email=email,
                    role=role_name,
                    tenant_id=str(tenant_id),
                )
                continue

            user = await user_repo.get_by_email(tenant_id, email)
            if user is None:
                user = await user_repo.create(
                    User(
                        tenant_id=tenant_id,
                        email=email,
                        password_hash=hash_password(password),
                        full_name=full_name,
                        is_active=True,
                        is_verified=True,
                    )
                )
                logger.info("seed.bridgeon.user.created", email=email, role=role_name)
            if user.id is None:
                raise RuntimeError(f"seeded user {email} has no id")

            # Enroll MFA with the fixed dev TOTP secret (idempotent - the same
            # secret is re-encrypted on every run, so challenge codes from the
            # documented secret always verify). MFA is mandatory in-app, so an
            # unenrolled account would be routed to forced /setup-mfa instead.
            await user_repo.update_mfa(
                user.id,
                mfa_enabled=True,
                mfa_secret=encrypt_mfa_secret(BRIDGEON_MFA_SECRET),
            )
            logger.info(
                "seed.bridgeon.mfa.enrolled",
                email=email,
                secret=BRIDGEON_MFA_SECRET,
            )

            membership = await membership_repo.get_by_user(user.id, tenant_id)
            if membership is None:
                await membership_repo.create(
                    Membership(
                        tenant_id=tenant_id,
                        user_id=user.id,
                        invited_email=user.email,
                        status=MembershipStatus.ACTIVE,
                        role_id=role.id,
                        joined_at=datetime.now(UTC),
                    )
                )
                logger.info("seed.bridgeon.membership.created", email=email)

            granted = await role_repo.grant_exists(
                user.id, role.id, ScopeType.TENANT, tenant_id
            )
            if not granted:
                await role_repo.grant_to_user(
                    user_id=user.id,
                    role_id=role.id,
                    tenant_id=tenant_id,
                    scope_id=tenant_id,
                )
                logger.info("seed.bridgeon.granted", role=role_name, email=email)

        await session.commit()


async def run_seed_bridgeon() -> None:
    """Run all bridgeon-solutions identity provisioning steps."""
    logger.info("seed.bridgeon.start")
    tenant_id = await seed_bridgeon_tenant()
    roles = await seed_bridgeon_roles(tenant_id)
    await seed_bridgeon_users(tenant_id, roles)
    logger.info(
        "seed.bridgeon.complete",
        tenant_id=str(tenant_id),
        roles=list(roles.keys()),
    )


if __name__ == "__main__":
    asyncio.run(run_seed_bridgeon())
