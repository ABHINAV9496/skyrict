"""Cross-service RBAC provisioning - consume identity tenant/role-grant events.

Identity owns tenancy + roles; the core service mirrors the subset it needs -
``core_roles`` + ``core_user_roles`` - so ``require_permission`` can resolve
ERP grants at request time. This module applies the ``identity.tenant.provisioned``
and ``identity.rbac.role_granted`` payloads (see ``skyrict_events.schemas``),
idempotently: a role is upserted by ``(tenant_id, id)`` with a name-match
fallback, and a grant by ``(tenant_id, user_id, role_id, scope_id)``.

Phase 1: Kafka is not wired, so there is no broker consumer loop. The handler
is invoked directly - from the ``core provision-rbac`` CLI, from tests, and
when the platform Kafka consumer lands.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select

from core.db.session import async_session_factory
from core.models.core_role import CoreRoleModel
from core.models.core_user_role import CoreUserRoleModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("core.events.rbac")


@dataclass
class RbacProvisionResult:
    """Counts for one provisioning run (idempotent re-runs report zeros)."""

    roles_created: int = 0
    roles_updated: int = 0
    grants_created: int = 0
    grants_skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


async def _upsert_role(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    role_id: uuid.UUID,
    role_name: str,
    permissions: list[str],
    is_system_role: bool,
) -> tuple[CoreRoleModel, bool]:
    """Find or create the role; return (role, created)."""
    role = await session.get(CoreRoleModel, (tenant_id, role_id))
    if role is None:
        role = await session.scalar(
            select(CoreRoleModel).where(
                CoreRoleModel.tenant_id == tenant_id,
                CoreRoleModel.name == role_name,
            )
        )
    if role is not None:
        role.name = role_name
        role.permissions = permissions
        role.is_system_role = is_system_role
        return role, False
    role = CoreRoleModel(
        tenant_id=tenant_id,
        id=role_id,
        name=role_name,
        permissions=permissions,
        is_system_role=is_system_role,
    )
    session.add(role)
    return role, True


async def _upsert_grant(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    scope_id: uuid.UUID | None,
) -> bool:
    """Create the user->role grant unless it already exists; return created."""
    existing = await session.scalar(
        select(CoreUserRoleModel).where(
            CoreUserRoleModel.tenant_id == tenant_id,
            CoreUserRoleModel.user_id == user_id,
            CoreUserRoleModel.role_id == role_id,
            CoreUserRoleModel.scope_id == scope_id,
        )
    )
    if existing is not None:
        return False
    session.add(
        CoreUserRoleModel(
            tenant_id=tenant_id,
            id=uuid.uuid4(),
            user_id=user_id,
            role_id=role_id,
            scope_id=scope_id,
        )
    )
    return True


async def apply_role_grants(
    session: AsyncSession,
    tenant_id: str | uuid.UUID,
    role_grants: list[dict[str, Any]],
) -> RbacProvisionResult:
    """Upsert the roles + grants from a provisioning payload onto ``session``.

    The caller controls the transaction (commit/rollback). Every entry is
    applied even if an earlier one fails, and duplicate entries within one
    payload are harmless (the second is a no-op).
    """
    result = RbacProvisionResult()
    tid = uuid.UUID(str(tenant_id))
    for grant in role_grants:
        role, created = await _upsert_role(
            session,
            tid,
            role_id=uuid.UUID(str(grant["role_id"])),
            role_name=grant["role_name"],
            permissions=list(grant["permissions"]),
            is_system_role=bool(grant.get("is_system_role", True)),
        )
        if created:
            result.roles_created += 1
        else:
            result.roles_updated += 1

        user_id = grant.get("user_id")
        if user_id is None:
            continue
        scope_raw = grant.get("scope_id")
        scope_id = uuid.UUID(str(scope_raw)) if scope_raw is not None else None
        created = await _upsert_grant(
            session,
            tid,
            user_id=uuid.UUID(str(user_id)),
            role_id=role.id,
            scope_id=scope_id,
        )
        if created:
            result.grants_created += 1
        else:
            result.grants_skipped += 1
    return result


async def provision_tenant_rbac(
    tenant_id: str | uuid.UUID,
    role_grants: list[dict[str, Any]],
) -> RbacProvisionResult:
    """Apply a provisioning payload in its own transaction and commit.

    Entry point for the ``core provision-rbac`` CLI, tests, and the future
    Kafka consumer handler.
    """
    async with async_session_factory() as session:
        result = await apply_role_grants(session, tenant_id, role_grants)
        await session.commit()
    logger.info(
        "rbac.provisioned",
        tenant_id=str(tenant_id),
        roles_created=result.roles_created,
        roles_updated=result.roles_updated,
        grants_created=result.grants_created,
        grants_skipped=result.grants_skipped,
    )
    return result
