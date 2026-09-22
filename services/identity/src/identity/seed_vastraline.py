"""Seed the ``vastraline-industries`` demo tenant (identity side).

Reusable, idempotent provisioning for the ``vastraline-industries`` demo
workspace used by the HR/Payroll/Finance walkthrough gates. The E2E compose
stack only seeds the ``default`` tenant; this module restores the demo
tenant that previously lived in the ad-hoc dev database.

What it creates (all scoped to the ``vastraline-industries`` tenant):

- the tenant itself (fixed slug ``vastraline-industries``, fixed UUID
  ``00000000-0000-0000-0000-000000000002``),
- the six ``SYSTEM_ROLE_DEFINITIONS`` roles,
- a realistic but entirely fake demo roster: eight identities on the
  reserved ``vastralineindustries.com`` domain spanning all six roles (owner,
  org admin, managers, standard users, auditor, self-service) - no real
  people,
- an active membership + tenant-scoped role grant for each user,
- MFA **enrolled** on every seeded account with the configured dev TOTP
  secret.

Converges pre-rebrand databases in place (SEC-CLEAN-001 follow-up): the
tenant is looked up by its fixed UUID first and slug/name are corrected when
they still carry the previous demo identity, and the eight roster accounts
are matched by ``full_name`` to re-point their email to the current demo
domain instead of being recreated - so existing dev DBs converge without a
primary-key crash or duplicate users.

Credentials are NEVER hardcoded here (SEC-CLEAN-001): the passwords and the
TOTP secret come from ``settings.SEED_VASTRALINE_*`` (values live only in the
gitignored ``services/identity/.env`` - never in the repo, the runbook, or
any script). The seeder **converges** both accounts to those values on every
run: existing users get their password hash and MFA secret re-applied, so
rotating credentials is simply *edit ``.env``, re-run this module*. Missing
values fail fast at startup - there is no fallback and no default.

Atomic (SEC-CLEAN-001): the whole run is ONE transaction with a single commit
at the end. Roles, memberships and grants are created together with users and
a completeness check runs before the commit - any missing role/membership/
grant raises and rolls back EVERYTHING, so the Entry C shape (users with no
RBAC rows) can never be persisted. A fully-seeded tenant that already exists
is left alone and re-runs simply converge + verify.

Usage:
    python -m identity.seed_vastraline
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("identity.seed.vastraline")

VASTRALINE_TENANT_ID = "00000000-0000-0000-0000-000000000002"
VASTRALINE_SLUG = "vastraline-industries"
VASTRALINE_NAME = "Vastraline Industries"

# (email, full_name, role_name) - passwords come from settings, per role.
# Synthetic identities only (vastralineindustries.com is a reserved, unclaimed
# demo domain): realistic fake people, never real personal data (SEC-CLEAN-001).
VASTRALINE_USERS: tuple[tuple[str, str, str], ...] = (
    ("aarav.deshmukh@vastralineindustries.com", "Aarav Deshmukh", "tenant_owner"),
    ("isha.fernandes@vastralineindustries.com", "Isha Fernandes", "organization_admin"),
    ("meera.iyer@vastralineindustries.com", "Meera Iyer", "department_manager"),
    ("ravi.kulkarni@vastralineindustries.com", "Ravi Kulkarni", "department_manager"),
    ("sana.sheikh@vastralineindustries.com", "Sana Sheikh", "standard_user"),
    ("arjun.rao@vastralineindustries.com", "Arjun Rao", "standard_user"),
    ("kavya.reddy@vastralineindustries.com", "Kavya Reddy", "auditor"),
    ("nisha.patel@vastralineindustries.com", "Nisha Patel", "employee_self_service"),
)

# role -> settings attribute holding that account's password. Owner and org
# admin have their own secrets; the staff roles share one demo password.
_VASTRALINE_PASSWORD_SETTING: dict[str, str] = {
    "tenant_owner": "SEED_VASTRALINE_OWNER_PASSWORD",
    "organization_admin": "SEED_VASTRALINE_ORG_ADMIN_PASSWORD",
    "department_manager": "SEED_VASTRALINE_TEAM_PASSWORD",
    "standard_user": "SEED_VASTRALINE_TEAM_PASSWORD",
    "auditor": "SEED_VASTRALINE_TEAM_PASSWORD",
    "employee_self_service": "SEED_VASTRALINE_TEAM_PASSWORD",
}


def credentials() -> tuple[dict[str, str], str]:
    """Load vastraline seed credentials from settings; refuse to run without them.

    Returns ``(passwords_by_role, mfa_secret)``. Any missing value or a value
    that violates the configured password policy raises before a single row
    is written, so the seeder can never silently fall back to a known
    plaintext.
    """
    passwords: dict[str, str] = {}
    missing: list[str] = []
    for role_name, setting in _VASTRALINE_PASSWORD_SETTING.items():
        value = getattr(settings, setting)
        if not value:
            missing.append(setting)
        else:
            validate_password_policy(value)
            passwords[role_name] = value
    mfa_secret = settings.SEED_VASTRALINE_MFA_SECRET
    if not mfa_secret:
        missing.append("SEED_VASTRALINE_MFA_SECRET")
    if missing:
        raise RuntimeError(
            "seed_vastraline requires the following env vars (set them in the "
            "gitignored services/identity/.env - never in the repo): " + ", ".join(missing)
        )
    return passwords, mfa_secret


async def seed_vastraline_tenant(session: AsyncSession) -> uuid.UUID:
    """Create the vastraline-industries tenant if absent; return its id.

    Looks the tenant up by its fixed UUID FIRST (not by slug): databases
    seeded before the rebrand hold the row with the same UUID but the old
    slug/name, and a re-run must converge those fields in place - creating a
    second row with the fixed UUID would crash on the PK, and looking up by
    slug alone could not see the pre-rebrand row.
    """
    tenant_id = uuid.UUID(VASTRALINE_TENANT_ID)
    repo = TenantRepository(session)
    existing = await repo.get_by_id(tenant_id)
    if existing is None:
        existing = await repo.get_by_slug(VASTRALINE_SLUG)
    if existing is not None and existing.id is not None:
        if existing.slug != VASTRALINE_SLUG or existing.name != VASTRALINE_NAME:
            await repo.rename(existing.id, slug=VASTRALINE_SLUG, name=VASTRALINE_NAME)
            logger.info(
                "seed.vastraline.tenant.converged",
                id=str(existing.id),
                slug=VASTRALINE_SLUG,
            )
        else:
            logger.info("seed.vastraline.tenant.exists", slug=VASTRALINE_SLUG, id=str(existing.id))
        return existing.id

    tenant = Tenant(
        name=VASTRALINE_NAME,
        slug=VASTRALINE_SLUG,
        is_active=True,
        plan_tier="free",
        id=tenant_id,
    )
    await repo.create(tenant)
    logger.info("seed.vastraline.tenant.created", slug=VASTRALINE_SLUG, id=str(tenant_id))
    return tenant_id


async def seed_vastraline_roles(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Role]:
    """Create missing system roles for the tenant; return a name -> role map.

    Per-name lookup: a tenant with a partial role set gets the missing roles
    added instead of being skipped. The caller verifies all six are present
    before committing.
    """
    repo = RoleRepository(session)
    roles_by_name: dict[str, Role] = {}
    for name, permissions in SYSTEM_ROLE_DEFINITIONS:
        role = await repo.get_by_name(tenant_id, name)
        if role is None:
            role = await repo.create(
                Role(
                    tenant_id=tenant_id,
                    name=name,
                    permissions=list(permissions),
                    is_system_role=True,
                )
            )
            logger.info("seed.vastraline.role.created", role=name, tenant_id=str(tenant_id))
        if role.id is None:
            raise RuntimeError(f"seeded role {name} has no id")
        roles_by_name[name] = role
    return roles_by_name


async def seed_vastraline_users(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    roles_by_name: dict[str, Role],
    *,
    passwords_by_role: dict[str, str],
    mfa_secret: str,
) -> None:
    """Create/refresh users, active memberships, and tenant-scoped grants.

    Idempotent, and **converging**: existing users get the configured
    password hash and MFA secret applied again, so re-running this after a
    ``.env`` change rotates the seeded accounts in place (SEC-CLEAN-001).

    Pre-rebrand convergence: an account that does not exist at the current
    roster email but does exist in the tenant under the same ``full_name`` is
    **remapped in place** (email re-pointed) instead of being created again,
    so existing dev DBs converge without duplicate users.

    Raises instead of silently skipping when a role or password is missing,
    so a partial run fails loudly and (inside :func:`seed_vastraline`) rolls
    back the entire transaction.
    """
    user_repo = UserRepository(session)
    membership_repo = MembershipRepository(session)
    role_repo = RoleRepository(session)

    for email, full_name, role_name in VASTRALINE_USERS:
        role = roles_by_name.get(role_name)
        if role is None or role.id is None:
            raise RuntimeError(
                f"seed_vastraline: role {role_name!r} missing for {email}; "
                "refusing to create the account without its RBAC target"
            )

        password = passwords_by_role.get(role_name)
        if not password:
            raise RuntimeError(
                f"seed_vastraline: no configured password for role {role_name!r}; "
                "refusing to create/update the account with an unknown password"
            )

        user = await user_repo.get_by_email(tenant_id, email)
        if user is None:
            # Rebrand convergence: pre-rebrand databases hold the same people
            # at the previous demo domain - re-point their email rather than
            # duplicating the account.
            legacy = await user_repo.get_by_full_name(tenant_id, full_name, exclude_email=email)
            if legacy is not None and legacy.id is not None:
                await user_repo.update_profile(legacy.id, email=email)
                user = legacy
                logger.info("seed.vastraline.user.email.remapped", email=email, role=role_name)
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
            logger.info("seed.vastraline.user.created", email=email, role=role_name)
        else:
            if user.id is None:
                raise RuntimeError(f"seeded user {email} has no id")
            # Rotation: converge the in-DB hash to the configured password.
            await user_repo.update_password_hash(user.id, hash_password(password))
            logger.info("seed.vastraline.user.password.rotated", email=email, role=role_name)
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
        logger.info("seed.vastraline.mfa.enrolled", email=email, secret_configured=True)

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
            logger.info("seed.vastraline.membership.created", email=email)

        granted = await role_repo.grant_exists(user.id, role.id, ScopeType.TENANT, tenant_id)
        if not granted:
            await role_repo.grant_to_user(
                user_id=user.id,
                role_id=role.id,
                tenant_id=tenant_id,
                scope_id=tenant_id,
            )
            logger.info("seed.vastraline.granted", role=role_name, email=email)


async def _verify_vastraline_rbac(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Completeness check: every seeded account must resolve to its RBAC row.

    Runs BEFORE the single commit in :func:`seed_vastraline` - any violation
    raises and rolls the whole transaction back, so the "users but no RBAC
    rows" shape (Entry C) cannot be persisted.
    """
    user_repo = UserRepository(session)
    membership_repo = MembershipRepository(session)
    role_repo = RoleRepository(session)

    violations: list[str] = []
    for email, _full_name, role_name in VASTRALINE_USERS:
        user = await user_repo.get_by_email(tenant_id, email)
        if user is None or user.id is None:
            violations.append(f"user {email} missing")
            continue

        role = await role_repo.get_by_name(tenant_id, role_name)
        if role is None or role.id is None:
            violations.append(f"role {role_name} missing")
            continue

        membership = await membership_repo.get_by_user(user.id, tenant_id)
        if membership is None:
            violations.append(f"membership missing for {email}")
        elif membership.status != MembershipStatus.ACTIVE:
            violations.append(f"membership not active for {email}")
        elif membership.role_id != role.id:
            violations.append(f"membership role mismatch for {email}")

        if not await role_repo.grant_exists(user.id, role.id, ScopeType.TENANT, tenant_id):
            violations.append(f"tenant-scoped grant missing for {email} ({role_name})")

    if violations:
        raise RuntimeError(
            "seed_vastraline completeness check failed - rolling back: " + "; ".join(violations)
        )
    logger.info(
        "seed.vastraline.verified",
        tenant_id=str(tenant_id),
        users=len(VASTRALINE_USERS),
        roles=len(SYSTEM_ROLE_DEFINITIONS),
    )


async def seed_vastraline(
    *,
    owner_password: str,
    org_admin_password: str,
    team_password: str,
    mfa_secret: str,
) -> None:
    """Seed/repair the vastraline-industries tenant in ONE atomic transaction.

    Tenants, roles, users, memberships, grants, and MFA enrollment are created
    (or converged) on a single session and committed once at the end; any
    failure (including a failed completeness check) rolls back everything.
    """
    passwords_by_role = {
        "tenant_owner": owner_password,
        "organization_admin": org_admin_password,
        "department_manager": team_password,
        "standard_user": team_password,
        "auditor": team_password,
        "employee_self_service": team_password,
    }
    async with async_session_factory() as session:
        tenant_id = await seed_vastraline_tenant(session)
        roles_by_name = await seed_vastraline_roles(session, tenant_id)
        if len(roles_by_name) != len(SYSTEM_ROLE_DEFINITIONS):
            raise RuntimeError(
                f"seed_vastraline: expected {len(SYSTEM_ROLE_DEFINITIONS)} roles, "
                f"got {len(roles_by_name)}"
            )
        await seed_vastraline_users(
            session,
            tenant_id,
            roles_by_name,
            passwords_by_role=passwords_by_role,
            mfa_secret=mfa_secret,
        )
        await _verify_vastraline_rbac(session, tenant_id)
        await session.commit()
    logger.info(
        "seed.vastraline.complete",
        tenant_id=str(tenant_id),
        roles=list(roles_by_name.keys()),
    )


async def run_seed_vastraline() -> None:
    """Load credentials from settings, then run the atomic seed."""
    logger.info("seed.vastraline.start")
    passwords_by_role, mfa_secret = credentials()
    await seed_vastraline(
        owner_password=passwords_by_role["tenant_owner"],
        org_admin_password=passwords_by_role["organization_admin"],
        team_password=passwords_by_role["employee_self_service"],
        mfa_secret=mfa_secret,
    )


if __name__ == "__main__":
    asyncio.run(run_seed_vastraline())
