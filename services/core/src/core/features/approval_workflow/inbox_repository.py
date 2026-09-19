"""Approval workflow inbox - pending approvals for a user (SKY-92).

The inbox answers "what needs my attention" for one user in a tenant:

- direct assignee: the user is a member of the step's resolved assignee set
  (role membership / permission grant / explicit user list);
- delegated: an active delegation FROM a member of the assignee set points at
  the user, with the grant's permission/resource_type scope matching the step
  and instance.

The query loads the tenant's pending instances + pending steps (bounded by
``limit``) and filters in Python using the RBAC membership and delegation
grant sets fetched with a handful of bulk probes. This keeps decision-time and
inbox eligibility identical: both use the live DB state rather than any
submission-time snapshot, so a revoked role or revoked delegation disappears
from the inbox immediately.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.rbac import grants_permission
from core.features.approval_workflow.delegation_repository import ApprovalDelegationRepository
from core.features.approval_workflow.models.delegation import ErpApprovalDelegationModel
from core.features.approval_workflow.models.instance import ErpApprovalWorkflowInstanceModel
from core.features.approval_workflow.models.step import ErpApprovalWorkflowStepModel
from core.models.core_role import CoreRoleModel
from core.models.core_user_role import CoreUserRoleModel


@dataclass(frozen=True)
class InboxItem:
    """One pending step the user may act on, with its instance context."""

    instance: ErpApprovalWorkflowInstanceModel
    step: ErpApprovalWorkflowStepModel
    #: "assignee" when the user is a direct member, "delegate" when acting
    #: through an active delegation.
    eligible_as: str
    #: the delegator for delegated items (None for direct assignee items).
    delegated_from: uuid.UUID | None = None


class ApprovalWorkflowInboxRepository:
    """Inbox probes; one repository per session."""

    def __init__(
        self,
        session: AsyncSession,
        delegation_repository: ApprovalDelegationRepository | None = None,
    ) -> None:
        self._db = session
        self._delegation_repo = delegation_repository

    async def list_pending_for_user(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        now: datetime,
        limit: int = 100,
    ) -> list[InboxItem]:
        """Pending approval steps the user can currently act on."""
        instances = await self._list_pending_instances(tenant_id, limit)
        if not instances:
            return []
        instance_ids = [instance.id for instance in instances]
        steps = await self._list_pending_steps(tenant_id, instance_ids)
        if not steps:
            return []

        user_roles = set(await self._resolve_user_roles(tenant_id, user_id))
        user_permissions = set(await self._resolve_user_permissions(tenant_id, user_id))

        delegations = (
            await self._delegation_repo.list_active_for_delegate(tenant_id, user_id, now)
            if self._delegation_repo is not None
            else []
        )
        delegator_roles: dict[uuid.UUID, set[str]] = {}
        delegator_permissions: dict[uuid.UUID, set[str]] = {}
        for grant in delegations:
            delegator = grant.delegator
            if delegator not in delegator_roles and delegator not in delegator_permissions:
                delegator_roles[delegator] = set(
                    await self._resolve_user_roles(tenant_id, delegator)
                )
                delegator_permissions[delegator] = set(
                    await self._resolve_user_permissions(tenant_id, delegator)
                )

        instances_by_id = {instance.id: instance for instance in instances}
        items: list[InboxItem] = []
        for step in steps:
            instance = instances_by_id.get(step.instance_id)
            if instance is None:
                continue
            direct = self._is_direct_assignee(
                user_id=user_id,
                user_roles=user_roles,
                user_permissions=user_permissions,
                step=step,
            )
            if direct:
                items.append(
                    InboxItem(
                        instance=instance,
                        step=step,
                        eligible_as="assignee",
                    )
                )
                continue
            delegated_from = self._match_delegation(
                delegations=delegations,
                delegator_roles=delegator_roles,
                delegator_permissions=delegator_permissions,
                instance=instance,
                step=step,
            )
            if delegated_from is not None:
                items.append(
                    InboxItem(
                        instance=instance,
                        step=step,
                        eligible_as="delegate",
                        delegated_from=delegated_from,
                    )
                )
        return items

    # ------------------------------------------------------------------ parts

    async def _list_pending_instances(
        self, tenant_id: uuid.UUID, limit: int
    ) -> list[ErpApprovalWorkflowInstanceModel]:
        result = await self._db.execute(
            select(ErpApprovalWorkflowInstanceModel)
            .where(
                ErpApprovalWorkflowInstanceModel.tenant_id == tenant_id,
                ErpApprovalWorkflowInstanceModel.status == "pending",
            )
            .order_by(
                ErpApprovalWorkflowInstanceModel.sla_due_at.is_(None),
                ErpApprovalWorkflowInstanceModel.sla_due_at,
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _list_pending_steps(
        self, tenant_id: uuid.UUID, instance_ids: list[uuid.UUID]
    ) -> list[ErpApprovalWorkflowStepModel]:
        result = await self._db.execute(
            select(ErpApprovalWorkflowStepModel)
            .where(
                ErpApprovalWorkflowStepModel.tenant_id == tenant_id,
                ErpApprovalWorkflowStepModel.instance_id.in_(instance_ids),
                ErpApprovalWorkflowStepModel.status == "pending",
            )
            .order_by(ErpApprovalWorkflowStepModel.step_index)
        )
        return list(result.scalars().all())

    async def _resolve_user_roles(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> list[str]:
        result = await self._db.execute(
            select(CoreRoleModel.name)
            .join(
                CoreUserRoleModel,
                and_(
                    CoreUserRoleModel.tenant_id == CoreRoleModel.tenant_id,
                    CoreUserRoleModel.role_id == CoreRoleModel.id,
                ),
            )
            .where(
                CoreUserRoleModel.tenant_id == tenant_id,
                CoreUserRoleModel.user_id == user_id,
            )
        )
        return [str(name) for name in result.scalars().all()]

    async def _resolve_user_permissions(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[str]:
        result = await self._db.execute(
            select(CoreRoleModel.permissions)
            .join(
                CoreUserRoleModel,
                and_(
                    CoreUserRoleModel.tenant_id == CoreRoleModel.tenant_id,
                    CoreUserRoleModel.role_id == CoreRoleModel.id,
                ),
            )
            .where(
                CoreUserRoleModel.tenant_id == tenant_id,
                CoreUserRoleModel.user_id == user_id,
            )
        )
        permissions: list[str] = []
        for row in result.scalars().all():
            permissions.extend(str(item) for item in row or [])
        return permissions

    @staticmethod
    def _is_direct_assignee(
        *,
        user_id: uuid.UUID,
        user_roles: set[str],
        user_permissions: set[str],
        step: ErpApprovalWorkflowStepModel,
    ) -> bool:
        """True when the user is a direct member of the step's assignee set."""
        if step.assignee_kind == "users":
            return user_id in {uuid.UUID(part) for part in step.assignee_value.split(",") if part}
        if step.assignee_kind == "role":
            return step.assignee_value in user_roles
        if step.assignee_kind == "permission":
            # ``grants_permission`` honours the owner wildcard ``"*"`` so the
            # inbox matches decision-time eligibility and ``require_permission``.
            return grants_permission(user_permissions, step.assignee_value)
        return False

    @staticmethod
    def _match_delegation(
        *,
        delegations: Sequence[ErpApprovalDelegationModel],
        delegator_roles: dict[uuid.UUID, set[str]],
        delegator_permissions: dict[uuid.UUID, set[str]],
        instance: ErpApprovalWorkflowInstanceModel,
        step: ErpApprovalWorkflowStepModel,
    ) -> uuid.UUID | None:
        """The delegator whose active grant lets ``user_id`` act on this step.

        Returns None when no grant matches. A grant matches when:

        - the delegator is a member of the step's direct assignee set
          (role member / permission grant / explicit user list);
        - the grant is not resource-scoped to a different resource type;
        - the grant is not permission-scoped to a different permission
          (permission-scoped grants only cover permission-keyed steps).
        """
        for grant in delegations:
            delegator = grant.delegator
            permission = grant.permission
            resource_type = grant.resource_type
            if resource_type is not None and resource_type != instance.resource_type:
                continue
            if permission is not None and step.assignee_kind != "permission":
                continue
            if permission is not None and not grants_permission([permission], step.assignee_value):
                continue
            if step.assignee_kind == "users":
                assignee_ids = [uuid.UUID(part) for part in step.assignee_value.split(",") if part]
                if delegator not in assignee_ids:
                    continue
            elif step.assignee_kind == "role":
                if step.assignee_value not in delegator_roles.get(delegator, set()):
                    continue
            elif step.assignee_kind == "permission":
                if not grants_permission(
                    delegator_permissions.get(delegator, set()), step.assignee_value
                ):
                    continue
            else:
                continue
            return delegator
        return None


__all__ = ["ApprovalWorkflowInboxRepository", "InboxItem"]
