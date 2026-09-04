"""Read-only RBAC resolution - the agent runtime's authorization path (SKY-59).

The core monolith resolves ERP permissions from the database at its proxy edge
(``core/db/rbac.py``); the ai-agent runtime re-resolves them IN this service so
agent tools can be scoped per tool without trusting a forwarded header. The
grants live in core's tables in the shared database, so this repository maps
the read-only projections (``models/core_rbac.py``) and runs the exact join
core's ``RbacRepository`` uses - a grant can only ever pull permissions from a
role in the same tenant.

Permissions are NEVER read from JWT claims: the claims name the subject and
tenant, the database names the permissions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, select

from ai_agent.graphs.security import grants_permission
from ai_agent.models.core_rbac import CoreRoleModel, CoreUserRoleModel

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


class PermissionRepository:
    """Resolve one caller's effective permission keys within a tenant."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve_user_permissions(
        self, *, user_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> list[str]:
        """Return the permission keys granted to ``user_id`` in ``tenant_id``.

        Joins ``core_user_roles`` -> ``core_roles`` on the composite key
        ``(tenant_id, role_id)`` so permissions can only come from a role in
        the same tenant.
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
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [permission for row in rows for permission in row]

    async def has_permission(
        self, *, user_id: uuid.UUID, tenant_id: uuid.UUID, required: str
    ) -> bool:
        """True when the caller holds *required* (exact key or owner wildcard)."""
        granted = await self.resolve_user_permissions(user_id=user_id, tenant_id=tenant_id)
        return grants_permission(granted, required)
