"""ERP role/permission resolution - the DB-resolved authorization path.

``require_permission`` (api/deps.py) resolves a user's grants from the database
at request time through :class:`RbacRepository` - permissions are NEVER read
from JWT claims. Roles are tenant-scoped, so resolution is scoped to the
request's tenant and the RLS policies (``app.current_tenant_id``) additionally
bound every query to that tenant.

Data scoping (OWNER/TEAM/ALL) follows the same discipline: a role name is
mapped to a :class:`DataScope` here - the ONE place that mapping lives - and
feature repositories receive only the resolved scope plus the user/team ids.
Repositories never hardcode role names, so a role change cannot silently
broaden a query.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, select

from core.core.permissions import WILDCARD
from core.domain.value_objects import DataScope
from core.models.core_role import CoreRoleModel
from core.models.core_user_role import CoreUserRoleModel

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession

# Single source of truth for role -> data scope. Matches identity's seeded
# SYSTEM_ROLE_DEFINITIONS (services/identity/src/identity/core/constants.py):
# owners/admins/auditors see the whole tenant, managers see their team, plain
# users see only their own rows. Unknown roles FAIL CLOSED to OWNER.
_SCOPE_BY_ROLE: dict[str, DataScope] = {
    "owner": DataScope.ALL,
    "tenant_owner": DataScope.ALL,
    "organization_admin": DataScope.ALL,
    "department_manager": DataScope.TEAM,
    "standard_user": DataScope.OWNER,
    "auditor": DataScope.ALL,
}

# Privilege ranking used when merging a user's roles (highest wins).
_SCOPE_RANK: dict[DataScope, int] = {
    DataScope.OWNER: 0,
    DataScope.TEAM: 1,
    DataScope.ALL: 2,
}


def resolve_data_scope(role_name: str) -> DataScope:
    """Map a role name to the data scope it grants.

    Unknown roles resolve to ``DataScope.OWNER`` (fail closed - a user can
    never see MORE than their role grants).
    """
    return _SCOPE_BY_ROLE.get(role_name, DataScope.OWNER)


def _merge_scopes(scopes: Iterable[DataScope]) -> DataScope:
    """Highest-privilege scope wins when a user holds several roles."""
    return max(scopes, key=lambda scope: _SCOPE_RANK[scope], default=DataScope.OWNER)


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

    async def resolve_user_scope(
        self, *, user_id: Any, tenant_id: Any
    ) -> tuple[DataScope, uuid.UUID | None]:
        """Return the user's effective ``(DataScope, scope_id)`` in ``tenant_id``.

        Merges the scopes of every tenant-scoped role the user holds with the
        highest privilege winning (a user granted both ``standard_user`` and
        ``organization_admin`` sees ALL, matching their combined grants).
        ``scope_id`` is the team/department attached to the grant
        (``core_user_roles.scope_id``) and is what TEAM-scope repository
        queries filter on; it is None when the user has no team grant.
        """
        stmt = (
            select(CoreRoleModel.name, CoreUserRoleModel.scope_id)
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
        rows = result.all()
        scopes = [resolve_data_scope(row[0]) for row in rows]
        team_id = next((row[1] for row in rows if row[1] is not None), None)
        return _merge_scopes(scopes), team_id
