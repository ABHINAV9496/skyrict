"""ERP role/permission resolution — the DB-resolved authorization path.

``require_permission`` (api/deps.py) resolves a user's grants from the database
at request time through :class:`RbacRepository` — permissions are NEVER read
from JWT claims. Roles are tenant-scoped, so resolution is scoped to the
request's tenant and the RLS policies (``app.current_tenant_id``) additionally
bound every query to that tenant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, select

from core.core.permissions import WILDCARD
from core.models.core_role import CoreRoleModel
from core.models.core_user_role import CoreUserRoleModel

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession


def grants_permission(granted: Iterable[str], required: str) -> bool:
    """True when the granted keys satisfy the required permission.

    The wildcard ``"*"`` (owner role) grants every catalogued permission;
    otherwise an exact key match is required. Fails closed: no match -> False.
    """
    keys = set(granted)
    return WILDCARD in keys or required in keys


class RbacRepository:
    """Resolve a user's effective permissions within a tenant."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve_user_permissions(self, *, user_id: Any, tenant_id: Any) -> list[str]:
        """Return the distinct permission keys granted to ``user_id`` in ``tenant_id``.

        Joins ``core_user_roles`` -> ``core_roles`` on the composite key
        ``(tenant_id, role_id)`` so a grant can only ever pull permissions from
        a role in the same tenant, then flattens each role's permission array.
        """
        stmt = (
            select(CoreRoleModel.permissions)
            .join(
                CoreUserRoleModel,
                and_(
                    CoreUserRoleModel.tenant_id == CoreRoleModel.tenant_id,
                    CoreUserRoleModel.role_id == CoreRoleModel.id,
                ),
            )
            .where(
                CoreUserRoleModel.user_id == user_id,
                CoreUserRoleModel.tenant_id == tenant_id,
            )
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [permission for row in rows for permission in row]
