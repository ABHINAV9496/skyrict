"""Approval workflow instance repository - DB access for SKY-92 engine state.

The data layer behind the engine: creates instances (with resolved steps +
submission transition), advances steps, records every state change as an
append-only transition, and resolves step assignees to concrete user ids.

Assignee resolution:

- ``role`` -> every tenant user holding a core role with that name
  (``core_user_roles`` joined to ``core_roles`` on the composite key).
- ``permission`` -> every tenant user whose roles grant the permission key.
- ``users`` -> the explicit user list from the definition (identity owns the
  users table, so there is no FK to validate membership; eligibility is
  checked by membership in the resolved list at decision time).

All probes are tenant-scoped (explicit ``tenant_id`` + RLS), matching the
finance repository's contract.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.core.permissions import WILDCARD
from core.features.approval_workflow.models.instance import ErpApprovalWorkflowInstanceModel
from core.features.approval_workflow.models.step import ErpApprovalWorkflowStepModel
from core.features.approval_workflow.models.transition import ErpApprovalTransitionModel
from core.models.core_role import CoreRoleModel
from core.models.core_user_role import CoreUserRoleModel


class ApprovalWorkflowInstanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # ---------------------------------------------------------- instance CRUD

    async def create_instance(
        self,
        *,
        tenant_id: uuid.UUID,
        definition_id: uuid.UUID,
        definition_version: int,
        resource_type: str,
        resource_id: uuid.UUID,
        submitted_by: uuid.UUID,
        now: datetime,
        steps: Sequence[dict[str, Any]],
        sla_due_at: datetime | None = None,
    ) -> ErpApprovalWorkflowInstanceModel:
        """Persist an instance with its resolved steps (atomic in one flush)."""
        instance = ErpApprovalWorkflowInstanceModel(
            tenant_id=tenant_id,
            definition_id=definition_id,
            definition_version=definition_version,
            resource_type=resource_type,
            resource_id=resource_id,
            status="pending",
            current_step_index=0,
            submitted_by=submitted_by,
            submitted_at=now,
            sla_due_at=sla_due_at,
            created_by=submitted_by,
            updated_by=submitted_by,
        )
        self._db.add(instance)
        await self._db.flush()
        for index, step in enumerate(steps):
            self._db.add(
                ErpApprovalWorkflowStepModel(
                    tenant_id=tenant_id,
                    instance_id=instance.id,
                    step_index=index,
                    step_key=step["step_key"],
                    assignee_kind=step["assignee_kind"],
                    assignee_value=step["assignee_value"],
                    status="pending",
                    original_assignee=step.get("original_assignee"),
                    assigned_to=step.get("assigned_to"),
                    sla_due_at=step.get("sla_due_at"),
                    assigned_at=now if step.get("assigned_to") else None,
                )
            )
        await self._db.flush()
        await self._db.refresh(instance)
        return instance

    async def get_instance(
        self, tenant_id: uuid.UUID, instance_id: uuid.UUID
    ) -> ErpApprovalWorkflowInstanceModel | None:
        result = await self._db.execute(
            select(ErpApprovalWorkflowInstanceModel).where(
                ErpApprovalWorkflowInstanceModel.tenant_id == tenant_id,
                ErpApprovalWorkflowInstanceModel.id == instance_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_steps(
        self, tenant_id: uuid.UUID, instance_id: uuid.UUID
    ) -> Sequence[ErpApprovalWorkflowStepModel]:
        result = await self._db.execute(
            select(ErpApprovalWorkflowStepModel)
            .where(
                ErpApprovalWorkflowStepModel.tenant_id == tenant_id,
                ErpApprovalWorkflowStepModel.instance_id == instance_id,
            )
            .order_by(ErpApprovalWorkflowStepModel.step_index)
        )
        return result.scalars().all()

    # ------------------------------------------------------------- decisions

    async def list_overdue_steps(
        self,
        *,
        tenant_id: uuid.UUID,
        now: datetime,
        limit: int,
    ) -> Sequence[ErpApprovalWorkflowStepModel]:
        """Pending current steps whose ``sla_due_at`` has passed (SLA breach).

        Targeted at the step the instance is actually waiting on
        (``step_index == instance.current_step_index``): future steps are not
        yet anyone's responsibility, so only the current pending step can
        escalate. Ordered most-overdue first, capped by ``limit``.
        """
        result = await self._db.execute(
            select(ErpApprovalWorkflowStepModel)
            .join(
                ErpApprovalWorkflowInstanceModel,
                and_(
                    ErpApprovalWorkflowInstanceModel.tenant_id
                    == ErpApprovalWorkflowStepModel.tenant_id,
                    ErpApprovalWorkflowInstanceModel.id == ErpApprovalWorkflowStepModel.instance_id,
                ),
            )
            .where(
                ErpApprovalWorkflowStepModel.tenant_id == tenant_id,
                ErpApprovalWorkflowInstanceModel.status == "pending",
                ErpApprovalWorkflowStepModel.status == "pending",
                ErpApprovalWorkflowStepModel.step_index
                == ErpApprovalWorkflowInstanceModel.current_step_index,
                ErpApprovalWorkflowStepModel.sla_due_at.is_not(None),
                ErpApprovalWorkflowStepModel.sla_due_at <= now,
            )
            .order_by(ErpApprovalWorkflowStepModel.sla_due_at)
            .limit(limit)
        )
        return result.scalars().all()

    async def mark_step_escalated(
        self,
        *,
        tenant_id: uuid.UUID,
        step_id: uuid.UUID,
    ) -> ErpApprovalWorkflowStepModel | None:
        """Mark a pending step ``escalated`` (SLA breach).

        Atomic AND idempotent: the ``UPDATE`` is conditional on the step still
        being ``pending``, so two concurrent escalation passes for the same
        step cannot both succeed -- the loser matches zero rows and returns
        ``None`` (the caller skips the transition log instead of double-logging
        a ``pending -> escalated`` transition).

        ``decided_by``/``decided_at`` stay unset: escalation is a supervisory
        signal, never a decision by an actor.
        """
        result = await self._db.execute(
            update(ErpApprovalWorkflowStepModel)
            .where(
                ErpApprovalWorkflowStepModel.tenant_id == tenant_id,
                ErpApprovalWorkflowStepModel.id == step_id,
                ErpApprovalWorkflowStepModel.status == "pending",
            )
            .values(status="escalated")
            .returning(ErpApprovalWorkflowStepModel)
            .execution_options(synchronize_session="fetch")
        )
        return result.scalars().one_or_none()

    async def list_pending_tenant_ids(self) -> list[uuid.UUID]:
        """Distinct tenant ids that have at least one ``pending`` instance.

        Cross-tenant probe for the background escalation worker (mirrors
        reporting's ``list_all_definition_pairs``): never tenant-scoped itself
        - the owner role bypasses RLS and this method must enumerate rows
        across all tenants so the worker can set each tenant's context.
        """
        result = await self._db.execute(
            select(ErpApprovalWorkflowInstanceModel.tenant_id)
            .where(ErpApprovalWorkflowInstanceModel.status == "pending")
            .distinct()
        )
        return [uuid.UUID(str(row)) for row in result.scalars().all()]

    async def update_step_decision(
        self,
        *,
        tenant_id: uuid.UUID,
        step_id: uuid.UUID,
        status: str,
        decided_by: uuid.UUID | None,
        decided_at: datetime,
        actor_type: str = "human",
        delegated_from: uuid.UUID | None = None,
    ) -> ErpApprovalWorkflowStepModel | None:
        """Approve/reject a step and record who decided.

        Atomic AND guarded: the UPDATE is conditional on the step still being
        ``pending``/``escalated``, so two concurrent decisions for the same
        step can never both land - the loser matches zero rows and returns
        ``None`` (the caller raises ``ConflictError``) instead of
        double-approving the resource and firing the module port twice.

        ``decided_by`` is None for system actors (auto approval, escalation) -
        the audit transition carries ``actor_type='system'`` instead.
        ``delegated_from`` preserves the delegator when a delegate decides
        (the ``assigned_to``/``delegated_from`` triple is the step's effective
        assignee history contract).
        """
        values: dict[str, object] = {
            "status": status,
            "decided_by": decided_by,
            "decided_at": decided_at,
        }
        if delegated_from is not None:
            values["assigned_to"] = decided_by
            values["delegated_from"] = delegated_from
        result = await self._db.execute(
            update(ErpApprovalWorkflowStepModel)
            .where(
                ErpApprovalWorkflowStepModel.tenant_id == tenant_id,
                ErpApprovalWorkflowStepModel.id == step_id,
                ErpApprovalWorkflowStepModel.status.in_(("pending", "escalated")),
            )
            .values(**values)
            .returning(ErpApprovalWorkflowStepModel)
            .execution_options(synchronize_session="fetch")
        )
        return result.scalars().one_or_none()

    async def update_instance_status(
        self,
        *,
        tenant_id: uuid.UUID,
        instance_id: uuid.UUID,
        status: str,
        current_step_index: int,
        updated_by: uuid.UUID,
        now: datetime,
    ) -> ErpApprovalWorkflowInstanceModel | None:
        instance = await self.get_instance(tenant_id, instance_id)
        if instance is None:
            return None
        instance.status = status
        instance.current_step_index = current_step_index
        instance.updated_by = updated_by
        if status in ("approved", "auto_approved", "rejected", "request_changes", "cancelled"):
            instance.completed_at = now
        await self._db.flush()
        await self._db.refresh(instance)
        return instance

    # ------------------------------------------------------------ transitions

    async def record_transition(
        self,
        *,
        tenant_id: uuid.UUID,
        workflow_instance_id: uuid.UUID,
        new_state: str,
        actor_type: str,
        actor_id: uuid.UUID | None = None,
        step_id: uuid.UUID | None = None,
        previous_state: str | None = None,
        reason: str | None = None,
        original_assignee: uuid.UUID | None = None,
        delegated_actor: uuid.UUID | None = None,
        context: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> ErpApprovalTransitionModel:
        """Append an immutable audit transition."""
        model = ErpApprovalTransitionModel(
            tenant_id=tenant_id,
            workflow_instance_id=workflow_instance_id,
            step_id=step_id,
            previous_state=previous_state,
            new_state=new_state,
            actor_id=actor_id,
            actor_type=actor_type,
            reason=reason,
            original_assignee=original_assignee,
            delegated_actor=delegated_actor,
            context=json.loads(json.dumps(context, default=str)) if context else None,
            occurred_at=occurred_at,
        )
        self._db.add(model)
        await self._db.flush()
        await self._db.refresh(model)
        return model

    async def list_transitions(
        self, tenant_id: uuid.UUID, instance_id: uuid.UUID
    ) -> Sequence[ErpApprovalTransitionModel]:
        result = await self._db.execute(
            select(ErpApprovalTransitionModel)
            .where(
                ErpApprovalTransitionModel.tenant_id == tenant_id,
                ErpApprovalTransitionModel.workflow_instance_id == instance_id,
            )
            .order_by(ErpApprovalTransitionModel.occurred_at, ErpApprovalTransitionModel.id)
        )
        return result.scalars().all()

    # ------------------------------------------------- assignee resolution

    async def resolve_role_members(self, tenant_id: uuid.UUID, role_name: str) -> list[uuid.UUID]:
        """Tenant user ids holding the named role (distinct)."""
        result = await self._db.execute(
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
                CoreRoleModel.name == role_name,
            )
            .distinct()
        )
        return [uuid.UUID(str(row)) for row in result.scalars().all()]

    async def resolve_permission_members(
        self, tenant_id: uuid.UUID, permission: str
    ) -> list[uuid.UUID]:
        """Tenant user ids whose roles grant ``permission`` (distinct)."""
        result = await self._db.execute(
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
                # The owner wildcard ``"*"`` grants every catalogued permission
                # (``core.db.rbac.grants_permission``); a permission-keyed step
                # must resolve wildcard holders too, or the tenant owner can
                # never be an approver. MyPy cannot type SQLAlchemy's ARRAY
                # ``any()`` operator; the repo uses this ignore on the identical
                # payroll_automation query.
                or_(
                    CoreRoleModel.permissions.any(permission),  # type: ignore[arg-type]
                    CoreRoleModel.permissions.any(WILDCARD),  # type: ignore[arg-type]
                ),
            )
            .distinct()
        )
        return [uuid.UUID(str(row)) for row in result.scalars().all()]
