"""Approval workflow delegation repository (SKY-92, delegation/inbox commit).

Runtime approver-level delegation: an approver grants another user the right
to act on their behalf, optionally scoped by ``permission`` and
``resource_type``, inside a revocation-able effective window. Delegation never
rewrites workflow definitions or historical transitions.

Engine integration: at decision time the engine resolves the step's direct
assignee set from the definition (role/permission/users) and then asks this
repository for the active delegates of those assignees ("who may act for an
assignee"). The inbox uses the reversed probe ("what may this user act on")
through :class:`ApprovalDelegationRepository.list_active_for_delegate`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.features.approval_workflow.models.delegation import ErpApprovalDelegationModel


class ApprovalDelegationRepository:
    """CRUD + probes for runtime delegations; one repository per session."""

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        delegator: uuid.UUID,
        delegate: uuid.UUID,
        created_by: uuid.UUID,
        now: datetime,
        permission: str | None = None,
        resource_type: str | None = None,
        effective_from: datetime | None = None,
        effective_to: datetime | None = None,
    ) -> ErpApprovalDelegationModel:
        """Persist an active delegation grant."""
        model = ErpApprovalDelegationModel(
            tenant_id=tenant_id,
            delegator=delegator,
            delegate=delegate,
            permission=permission,
            resource_type=resource_type,
            effective_from=effective_from or now,
            effective_to=effective_to,
            created_by=created_by,
        )
        self._db.add(model)
        await self._db.flush()
        await self._db.refresh(model)
        return model

    async def revoke(
        self,
        *,
        tenant_id: uuid.UUID,
        delegation_id: uuid.UUID,
        revoked_at: datetime,
    ) -> ErpApprovalDelegationModel | None:
        """Revoke a delegation (soft revoke - the row is preserved for audit)."""
        result = await self._db.execute(
            select(ErpApprovalDelegationModel).where(
                ErpApprovalDelegationModel.tenant_id == tenant_id,
                ErpApprovalDelegationModel.id == delegation_id,
                ErpApprovalDelegationModel.revoked_at.is_(None),
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        model.revoked_at = revoked_at
        await self._db.flush()
        await self._db.refresh(model)
        return model

    async def list_active_for_delegate(
        self, tenant_id: uuid.UUID, delegate: uuid.UUID, now: datetime
    ) -> list[ErpApprovalDelegationModel]:
        """Active delegations where ``delegate`` may act (window + not revoked)."""
        result = await self._db.execute(
            select(ErpApprovalDelegationModel).where(
                ErpApprovalDelegationModel.tenant_id == tenant_id,
                ErpApprovalDelegationModel.delegate == delegate,
                ErpApprovalDelegationModel.revoked_at.is_(None),
                ErpApprovalDelegationModel.effective_from <= now,
                or_(
                    ErpApprovalDelegationModel.effective_to.is_(None),
                    ErpApprovalDelegationModel.effective_to >= now,
                ),
            )
        )
        return list(result.scalars().all())

    async def resolve_active_delegators(
        self,
        *,
        tenant_id: uuid.UUID,
        delegate: uuid.UUID,
        now: datetime,
    ) -> list[uuid.UUID]:
        """Ids of users whose active, non-revoked delegation includes ``delegate``."""
        models = await self.list_active_for_delegate(tenant_id, delegate, now)
        return list({model.delegator for model in models})

    async def list_grants_from_delegators(
        self,
        *,
        tenant_id: uuid.UUID,
        delegators: list[uuid.UUID],
        now: datetime,
    ) -> list[ErpApprovalDelegationModel]:
        """Active grants FROM any of ``delegators`` (engine-side eligibility probe).

        Returns every delegation whose delegator is in the set and that is
        active at ``now``; scope filtering (permission/resource_type) is done by
        the engine against the step/instance it is resolving.
        """
        if not delegators:
            return []
        result = await self._db.execute(
            select(ErpApprovalDelegationModel).where(
                ErpApprovalDelegationModel.tenant_id == tenant_id,
                ErpApprovalDelegationModel.delegator.in_(delegators),
                ErpApprovalDelegationModel.revoked_at.is_(None),
                ErpApprovalDelegationModel.effective_from <= now,
                or_(
                    ErpApprovalDelegationModel.effective_to.is_(None),
                    ErpApprovalDelegationModel.effective_to >= now,
                ),
            )
        )
        return list(result.scalars().all())


__all__ = ["ApprovalDelegationRepository"]
