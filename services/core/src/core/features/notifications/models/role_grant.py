"""Reverse RBAC lookups - resolve permission/role to user ids.

``RbacRepository`` resolves a user's grants; this module resolves the
reverse: every user who holds a given set of permissions or roles within a
tenant. Used by the notification producer SDK to materialise recipient rows
from audience specs.
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models.core_role import CoreRoleModel
from core.models.core_user_role import CoreUserRoleModel


async def user_ids_for_permissions(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    permission_keys: list[str],
) -> list[uuid.UUID]:
    """Distinct users who hold any of the given permission keys in this tenant.

    Uses ``CoreRoleModel.permissions`` (ARRAY(String)) with PostgreSQL
    ``@>`` (contains) to find roles that grant at least one of the keys,
    then joins through ``core_user_roles`` for the user ids.
    """
    if not permission_keys:
        return []

    # Build OR predicates so each permission key is checked against the
    # ARRAY column independently: ``permissions @> ARRAY[key]``.
    array_contains = [CoreRoleModel.permissions.contains([key]) for key in permission_keys]

    stmt = (
        select(CoreUserRoleModel.user_id)
        .join(
            CoreRoleModel,
            and_(
                CoreUserRoleModel.tenant_id == CoreRoleModel.tenant_id,
                CoreUserRoleModel.role_id == CoreRoleModel.id,
            ),
        )
        .where(
            CoreUserRoleModel.tenant_id == tenant_id,
            or_(*array_contains),
        )
        .distinct()
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def user_ids_for_roles(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    role_names: list[str],
) -> list[uuid.UUID]:
    """Distinct users who hold any of the named roles in this tenant."""
    if not role_names:
        return []

    stmt = (
        select(CoreUserRoleModel.user_id)
        .join(
            CoreRoleModel,
            and_(
                CoreUserRoleModel.tenant_id == CoreRoleModel.tenant_id,
                CoreUserRoleModel.role_id == CoreRoleModel.id,
            ),
        )
        .where(
            CoreUserRoleModel.tenant_id == tenant_id,
            CoreRoleModel.name.in_(role_names),
        )
        .distinct()
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]
