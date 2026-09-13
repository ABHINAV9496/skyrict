"""Approval workflow engine (SKY-92) - submission, decisions and audit.

The engine is deliberately resource-agnostic: it never interprets "journal
entry" or "payroll run" semantics. A module submits a resource
(``resource_type`` + ``resource_id`` + routing amount), the engine resolves
steps from the active definition, and modules observe the outcome through
their own resource port (Commit: routing/auto-approve + module ports).

Commit scope (engine + audit):

- ``submit`` - create an instance, resolve each step's assignee to concrete
  user ids (role -> role members, permission -> permission members, users ->
  explicit list), compute SLA due times, and record the submission audit
  transition. Instances are created ``pending``; amount-condition routing and
  auto-approval arrive in the routing/auto-approve commit.
- ``decide`` - approve / reject / request-changes the current step. The actor
  must be a member of the step's resolved assignee set (delegation arrives in
  the delegation/inbox commit). Every decision is an append-only transition;
  the instance advances to the next pending step and completes
  (``approved``/``rejected``/``request_changes``) after the final step.

All decisions are made against the DB-resolved RBAC state at decision time
(never from JWT claims), matching ``require_permission``.

The engine takes an injectable ``now`` clock so SLA computations and audit
timestamps are deterministic in tests.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from core.features.approval_workflow.dsl import (
    PermissionAssignee,
    RoleAssignee,
    UserListAssignee,
    WorkflowDefinition,
    WorkflowStep,
)
from core.features.approval_workflow.instance_repository import (
    ApprovalWorkflowInstanceRepository,
)
from core.features.approval_workflow.models.instance import ErpApprovalWorkflowInstanceModel
from core.features.approval_workflow.models.step import ErpApprovalWorkflowStepModel
from skyrict_common.exceptions import ConflictError, NotFoundError, PermissionDeniedError

# Statuses the engine owns.
INSTANCE_PENDING = "pending"
INSTANCE_APPROVED = "approved"
INSTANCE_REJECTED = "rejected"
INSTANCE_REQUEST_CHANGES = "request_changes"

STEP_PENDING = "pending"
STEP_APPROVED = "approved"
STEP_REJECTED = "rejected"

ASSIGNEE_DELIMITER = ","

# module ports / routed statuses glued in later commits.
INSTANCE_AUTO_APPROVED = "auto_approved"
STEP_SKIPPED = "skipped"
STEP_ESCALATED = "escalated"

#: actor types recorded on audit transitions
ACTOR_HUMAN = "human"
ACTOR_SYSTEM = "system"


@dataclass(frozen=True)
class SubmitResult:
    instance: ErpApprovalWorkflowInstanceModel
    steps: list[ErpApprovalWorkflowStepModel]


@dataclass(frozen=True)
class DecisionResult:
    instance: ErpApprovalWorkflowInstanceModel
    step: ErpApprovalWorkflowStepModel
    instance_completed: bool


def _assignee_value(step: WorkflowStep) -> tuple[str, str]:
    """Map a DSL assignee spec to the step's ``(assignee_kind, assignee_value)``.

    Role/permission store the name/key as-is; user lists are serialized as a
    comma-separated UUID string so they fit the ``String(255)`` column.
    """
    spec = step.assignee
    if isinstance(spec, RoleAssignee):
        return "role", spec.role
    if isinstance(spec, PermissionAssignee):
        return "permission", spec.permission
    if isinstance(spec, UserListAssignee):
        return "users", ASSIGNEE_DELIMITER.join(str(user_id) for user_id in spec.user_ids)
    raise TypeError(f"unsupported assignee spec: {type(spec).__name__}")


class ApprovalEngine:
    """Stateful engine facade over a repository; one engine per request/session."""

    def __init__(
        self,
        repository: ApprovalWorkflowInstanceRepository,
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._repo = repository
        self._now = now

    async def submit(
        self,
        *,
        tenant_id: uuid.UUID,
        definition: WorkflowDefinition,
        definition_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        amount: Any | None,
        submitted_by: uuid.UUID,
    ) -> SubmitResult:
        """Create a pending instance for a resource.

        Steps are resolved in definition order; each step's ``sla`` (when
        present) sets ``sla_due_at = now + hours``. The submission transition
        is recorded with actor type ``system`` (the submitter is captured on
        the instance itself).
        """
        now = self._now()
        steps: list[dict[str, Any]] = []
        for step in definition.steps:
            kind, value = _assignee_value(step)
            sla_due_at = now + timedelta(hours=step.sla.hours) if step.sla else None
            steps.append(
                {
                    "step_key": step.key,
                    "assignee_kind": kind,
                    "assignee_value": value,
                    "sla_due_at": sla_due_at,
                }
            )
        instance = await self._repo.create_instance(
            tenant_id=tenant_id,
            definition_id=definition_id,
            definition_version=definition.version,
            resource_type=resource_type,
            resource_id=resource_id,
            submitted_by=submitted_by,
            now=now,
            steps=steps,
        )
        await self._repo.record_transition(
            tenant_id=tenant_id,
            workflow_instance_id=instance.id,
            new_state="submitted",
            actor_type=ACTOR_SYSTEM,
            actor_id=None,
            context={"amount": str(amount) if amount is not None else None},
            occurred_at=now,
        )
        instance_steps = await self._repo.list_steps(tenant_id, instance.id)
        return SubmitResult(instance=instance, steps=list(instance_steps))

    async def decide(
        self,
        *,
        tenant_id: uuid.UUID,
        instance_id: uuid.UUID,
        actor_id: uuid.UUID,
        decision: str,
        reason: str | None = None,
        step_index: int | None = None,
    ) -> DecisionResult:
        """Approve / reject / request-changes the current (or named) step.

        Validations (all fail closed):

        - instance exists and is ``pending``;
        - the target step exists, belongs to the instance, and is pending;
        - ``actor_id`` is a member of the step's resolved assignee set
          (role members / permission members / explicit user list).

        Every decision appends an audit transition with actor type ``human``
        and advances the instance to the next pending step; after the final
        step the instance completes as ``approved`` / ``rejected`` /
        ``request_changes``.
        """
        now = self._now()
        instance = await self._repo.get_instance(tenant_id, instance_id)
        if instance is None:
            raise NotFoundError(f"Approval instance {instance_id} not found")
        if instance.status != INSTANCE_PENDING:
            raise ConflictError(
                f"Approval instance {instance_id} is {instance.status}, not pending"
            )

        if step_index is None:
            step_index = instance.current_step_index
        steps = await self._repo.list_steps(tenant_id, instance_id)
        target = next((s for s in steps if s.step_index == step_index), None)
        if target is None:
            raise NotFoundError(f"Step index {step_index} not found on instance {instance_id}")
        if target.status != STEP_PENDING:
            raise ConflictError(f"Step '{target.step_key}' is {target.status}, not pending")

        assignee_ids = await self._step_assignee_ids(tenant_id, target)
        if actor_id not in assignee_ids:
            raise PermissionDeniedError(
                f"User {actor_id} is not an assignee of step '{target.step_key}'"
            )

        if decision not in (STEP_APPROVED, STEP_REJECTED, "request_changes"):
            raise ConflictError(f"Unsupported decision: {decision!r}")

        step_status = STEP_APPROVED if decision == STEP_APPROVED else STEP_REJECTED
        if decision == "request_changes":
            step_status = "rejected"

        step = await self._repo.update_step_decision(
            tenant_id=tenant_id,
            step_id=target.id,
            status=step_status,
            decided_by=actor_id,
            decided_at=now,
            actor_type=ACTOR_HUMAN,
        )
        if step is None:
            raise NotFoundError(f"Step {target.id} not found")

        await self._repo.record_transition(
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            step_id=step.id,
            previous_state=STEP_PENDING,
            new_state=decision,
            actor_id=actor_id,
            actor_type=ACTOR_HUMAN,
            reason=reason,
            original_assignee=actor_id,
            occurred_at=now,
        )

        # Advance to the next pending step or complete.
        next_pending = next(
            (s for s in steps if s.status == STEP_PENDING and s.step_index > target.step_index),
            None,
        )
        if next_pending is not None:
            await self._repo.update_instance_status(
                tenant_id=tenant_id,
                instance_id=instance_id,
                status=INSTANCE_PENDING,
                current_step_index=next_pending.step_index,
                updated_by=actor_id,
                now=now,
            )
            updated = await self._repo.get_instance(tenant_id, instance_id)
            if updated is None:
                raise NotFoundError(f"Approval instance {instance_id} not found")
            return DecisionResult(instance=updated, step=step, instance_completed=False)

        final_status = {"approved": INSTANCE_APPROVED, "rejected": INSTANCE_REJECTED}[decision]
        await self._repo.update_instance_status(
            tenant_id=tenant_id,
            instance_id=instance_id,
            status=final_status,
            current_step_index=target.step_index,
            updated_by=actor_id,
            now=now,
        )
        updated = await self._repo.get_instance(tenant_id, instance_id)
        if updated is None:
            raise NotFoundError(f"Approval instance {instance_id} not found")
        return DecisionResult(instance=updated, step=step, instance_completed=True)

    async def _step_assignee_ids(
        self, tenant_id: uuid.UUID, target: ErpApprovalWorkflowStepModel
    ) -> list[uuid.UUID]:
        """Resolve the target step's assignee set from its stored spec.

        Role/permission kinds are resolved against the DB at decision time
        (never from submission-time snapshots): a user granted the role or
        permission after submission can decide, and a revoked user cannot.
        User lists were stored comma-separated at submission time (identity
        owns the users table - no FK to validate against).
        """
        if target.assignee_kind == "role":
            return await self._repo.resolve_role_members(tenant_id, target.assignee_value)
        if target.assignee_kind == "permission":
            return await self._repo.resolve_permission_members(tenant_id, target.assignee_value)
        if target.assignee_kind == "users":
            return [
                uuid.UUID(part) for part in target.assignee_value.split(ASSIGNEE_DELIMITER) if part
            ]
        raise TypeError(f"unsupported stored assignee kind: {target.assignee_kind}")
