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
- an active membership + tenant-scoped role grant for each user,
- MFA **enrolled** on both accounts with the configured dev TOTP secret.

Credentials are NEVER hardcoded here (SEC-CLEAN-001): the passwords and the
TOTP secret come from ``settings.SEED_BRIDGEON_*`` (values live only in the
gitignored ``services/identity/.env`` - never in the repo, the runbook, or
any script). The seeder **converges** both accounts to those values on every
run: existing users get their password hash and MFA secret re-applied, so
rotating credentials is simply *edit ``.env``, re-run this module*. Missing
values fail fast at startup - there is no fallback and no default.

Idempotent - safe to re-run; a tenant that already exists is left alone and
its roles/memberships/grants are preserved.

Usage:
    python -m identity.seed_bridgeon
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog

from identity.core.config import settings
from identity.core.constants import SYSTEM_ROLE_DEFINITIONS
from identity.core.security import encrypt_mfa_secret, hash_password, validate_password_policy
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

# (email, full_name, role_name) - passwords come from settings, per role.
BRIDGEON_USERS: tuple[tuple[str, str, str], ...] = (
    ("abhikrishna616@gmail.com", "Abhikrishna", "tenant_owner"),
    ("admin@bridgeon.io", "Bridgeon Admin", "organization_admin"),
)

# role -> settings attribute holding that account's password.
_BRIDGEON_PASSWORD_SETTING: dict[str, str] = {
    "tenant_owner": "SEED_BRIDGEON_OWNER_PASSWORD",
    "organization_admin": "SEED_BRIDGEON_ORG_ADMIN_PASSWORD",
}


def credentials() -> tuple[dict[str, str], str]:
    """Load bridgeon seed credentials from settings; refuse to run without them.

    Returns ``(passwords_by_role, mfa_secret)``. Any missing value or a value
    that violates the configured password policy raises before a single row
    is written, so the seeder can never silently fall back to a known
    plaintext.
    """
    passwords: dict[str, str] = {}
    missing: list[str] = []
    for role_name, setting in _BRIDGEON_PASSWORD_SETTING.items():
        value = getattr(settings, setting)
        if not value:
            missing.append(setting)
        else:
            validate_password_policy(value)
            passwords[role_name] = value
    mfa_secret = settings.SEED_BRIDGEON_MFA_SECRET
    if not mfa_secret:
        missing.append("SEED_BRIDGEON_MFA_SECRET")
    if missing:
        raise RuntimeError(
            "seed_bridgeon requires the following env vars (set them in the "
            "gitignored services/identity/.env - never in the repo): "
            + ", ".join(missing)
        )
    return passwords, mfa_secret


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
    """Create missing system roles for the tenant; return a name -> role map."""
    async with async_session_factory() as session:
        repo = RoleRepository(session)
        existing = {
            role.name: role
            for role in await repo.list_by_tenant(tenant_id, limit=1000)
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
    *,
    passwords_by_role: dict[str, str],
    mfa_secret: str,
) -> None:
    """Create/refresh users, active memberships, and tenant-scoped grants.

    Idempotent, and **converging**: existing users get the configured
    password hash and MFA secret applied again, so re-running this after a
    ``.env`` change rotates the two accounts in place (SEC-CLEAN-001).
    """
    async with async_session_factory() as session:
        user_repo = UserRepository(session)
        membership_repo = MembershipRepository(session)
        role_repo = RoleRepository(session)

        for email, full_name, role_name in BRIDGEON_USERS:
            role = roles_by_name.get(role_name)
            if role is None or role.id is None:
                logger.warning(
                    "seed.bridgeon.role.missing",
                    email=email,
                    role=role_name,
                    tenant_id=str(tenant_id),
                )
                continue

            password = passwords_by_role.get(role_name)
            if not password:
                raise RuntimeError(
                    f"seed_bridgeon: no configured password for role {role_name!r}; "
                    "refusing to create/update the account with an unknown password"
                )

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
            else:
                # Rotation: converge the in-DB hash to the configured password.
                await user_repo.update_password_hash(user.id, hash_password(password))
                logger.info("seed.bridgeon.user.password.rotated", email=email, role=role_name)
            if user.id is None:
                raise RuntimeError(f"seeded user {email} has no id")

            # Enroll/refresh MFA with the configured dev TOTP secret. MFA is
            # mandatory in-app, so an unenrolled account would be routed to
            # forced /setup-mfa instead of the headless gate flow.
            await user_repo.update_mfa(
                user.id,
                mfa_enabled=True,
                mfa_secret=encrypt_mfa_secret(mfa_secret),
            )
            logger.info(
                "seed.bridgeon.mfa.enrolled",
                email=email,
                secret_configured=True,
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

            granted = await role_repo.grant_exists(user.id, role.id, ScopeType.TENANT, tenant_id)
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
    passwords_by_role, mfa_secret = credentials()
    tenant_id = await seed_bridgeon_tenant()
    roles = await seed_bridgeon_roles(tenant_id)
    await seed_bridgeon_users(
        tenant_id,
        roles,
        passwords_by_role=passwords_by_role,
        mfa_secret=mfa_secret,
    )
    logger.info(
        "seed.bridgeon.complete",
        tenant_id=str(tenant_id),
        roles=list(roles.keys()),
    )


if __name__ == "__main__":
    asyncio.run(run_seed_bridgeon())