"""Approval workflow definition repository - DB access for SKY-92.

The feature's only DB-touching code for workflow definitions. Owns the
versioned lifecycle of ``erp_approval_workflow_definitions``:

- **draft** - newest writable version for a ``resource_type``. Creating a
  draft computes ``version = max(version)+1`` so edits never rewrite history.
- **active** - sealed (immutable) definition the engine executes. Sealing is
  an explicit ``activate`` call because the DSL is Pydantic-validated at the
  service layer before it is persisted here.
- **retired** - soft-removed from routing (new instances never use it).

All probes are tenant-scoped (explicit ``tenant_id`` + RLS), matching the
finance repository's contract.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.features.approval_workflow.models.definition import ErpApprovalWorkflowDefinitionModel


class ApprovalWorkflowDefinitionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def next_version(self, tenant_id: uuid.UUID, resource_type: str) -> int:
        """Next version number for a (resource_type) definition family."""
        latest = await self._db.execute(
            select(func.max(ErpApprovalWorkflowDefinitionModel.version)).where(
                ErpApprovalWorkflowDefinitionModel.tenant_id == tenant_id,
                ErpApprovalWorkflowDefinitionModel.resource_type == resource_type,
            )
        )
        current = latest.scalar_one()
        return int(current or 0) + 1

    async def create_draft(
        self,
        *,
        tenant_id: uuid.UUID,
        name: str,
        resource_type: str,
        definition: dict[str, Any],
        created_by: uuid.UUID | None = None,
    ) -> ErpApprovalWorkflowDefinitionModel:
        """Persist a validated DSL document as the newest draft version."""
        version = await self.next_version(tenant_id, resource_type)
        model = ErpApprovalWorkflowDefinitionModel(
            tenant_id=tenant_id,
            name=name,
            resource_type=resource_type,
            version=version,
            definition=definition,
            status="draft",
            created_by=created_by,
            updated_by=created_by,
        )
        self._db.add(model)
        await self._db.flush()
        await self._db.refresh(model)
        return model

    async def get(
        self, tenant_id: uuid.UUID, definition_id: uuid.UUID
    ) -> ErpApprovalWorkflowDefinitionModel | None:
        result = await self._db.execute(
            select(ErpApprovalWorkflowDefinitionModel).where(
                ErpApprovalWorkflowDefinitionModel.tenant_id == tenant_id,
                ErpApprovalWorkflowDefinitionModel.id == definition_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_version(
        self, tenant_id: uuid.UUID, resource_type: str, version: int
    ) -> ErpApprovalWorkflowDefinitionModel | None:
        result = await self._db.execute(
            select(ErpApprovalWorkflowDefinitionModel).where(
                ErpApprovalWorkflowDefinitionModel.tenant_id == tenant_id,
                ErpApprovalWorkflowDefinitionModel.resource_type == resource_type,
                ErpApprovalWorkflowDefinitionModel.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def get_latest(
        self, tenant_id: uuid.UUID, resource_type: str
    ) -> ErpApprovalWorkflowDefinitionModel | None:
        """Newest version of a definition family, regardless of status."""
        result = await self._db.execute(
            select(ErpApprovalWorkflowDefinitionModel)
            .where(
                ErpApprovalWorkflowDefinitionModel.tenant_id == tenant_id,
                ErpApprovalWorkflowDefinitionModel.resource_type == resource_type,
            )
            .order_by(ErpApprovalWorkflowDefinitionModel.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active(
        self, tenant_id: uuid.UUID, resource_type: str
    ) -> ErpApprovalWorkflowDefinitionModel | None:
        """Sealed definition the engine executes for a resource_type."""
        result = await self._db.execute(
            select(ErpApprovalWorkflowDefinitionModel).where(
                ErpApprovalWorkflowDefinitionModel.tenant_id == tenant_id,
                ErpApprovalWorkflowDefinitionModel.resource_type == resource_type,
                ErpApprovalWorkflowDefinitionModel.status == "active",
            )
        )
        return result.scalars().first()

    async def list(
        self,
        tenant_id: uuid.UUID,
        resource_type: str | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[ErpApprovalWorkflowDefinitionModel]:
        stmt = select(ErpApprovalWorkflowDefinitionModel).where(
            ErpApprovalWorkflowDefinitionModel.tenant_id == tenant_id
        )
        if resource_type:
            stmt = stmt.where(ErpApprovalWorkflowDefinitionModel.resource_type == resource_type)
        stmt = (
            stmt.order_by(
                ErpApprovalWorkflowDefinitionModel.resource_type,
                ErpApprovalWorkflowDefinitionModel.version.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self._db.execute(stmt)
        return result.scalars().all()

    async def activate(
        self,
        tenant_id: uuid.UUID,
        definition_id: uuid.UUID,
        updated_by: uuid.UUID | None = None,
    ) -> ErpApprovalWorkflowDefinitionModel | None:
        """Seal a draft as the executable definition for its resource_type.

        The engine routes new instances to the single active version. An
        existing active version is retired first (soft removal); the seal is
        the point of no return - the JSONB body of an active definition is
        never edited in place.
        """
        model = await self.get(tenant_id, definition_id)
        if model is None or model.status != "draft":
            return None
        active_rows = await self._db.execute(
            select(ErpApprovalWorkflowDefinitionModel).where(
                ErpApprovalWorkflowDefinitionModel.tenant_id == tenant_id,
                ErpApprovalWorkflowDefinitionModel.resource_type == model.resource_type,
                ErpApprovalWorkflowDefinitionModel.status == "active",
            )
        )
        for prior in active_rows.scalars().all():
            prior.status = "retired"
        model.status = "active"
        model.updated_by = updated_by
        await self._db.flush()
        await self._db.refresh(model)
        return model

    async def retire(
        self,
        tenant_id: uuid.UUID,
        definition_id: uuid.UUID,
        updated_by: uuid.UUID | None = None,
    ) -> ErpApprovalWorkflowDefinitionModel | None:
        model = await self.get(tenant_id, definition_id)
        if model is None or model.status != "active":
            return None
        model.status = "retired"
        model.updated_by = updated_by
        await self._db.flush()
        await self._db.refresh(model)
        return model
