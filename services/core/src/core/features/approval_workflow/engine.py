"""Approval workflow engine (SKY-92) - submission, decisions and audit.

The engine is deliberately resource-agnostic: it never interprets "journal
entry" or "payroll run" semantics. A module submits a resource
(``resource_type`` + ``resource_id`` + routing amount), the engine resolves
steps from the active definition, and modules observe the outcome through
:class:`ApprovalResourcePort` (implemented per module at the composition
root, mirroring payroll's ``PayslipApprovedNotifierPort``).

Behavior:

- ``submit`` - create an instance, store each step's assignee spec (role ->
  role name, permission -> permission key, users -> explicit list), compute SLA
  due times, and record the submission audit transition. Assignee *membership*
  is resolved at decision time against the DB, never from submission-time
  snapshots. Auto-approval rules are then evaluated in definition order:
  each step whose ``auto_approval.when`` matches the routing amount is
  approved by the system actor; when every step auto-approves, the instance
  completes as ``auto_approved`` and the module port's ``on_approved``
  (system actor) is called; the first non-matching step becomes the pending
  queue.
- ``decide`` - approve / reject / request-changes the current step. The actor
  must be a member of the step's resolved assignee set, or an active delegate
  of such a member (runtime approver-level delegation, resolved at decision
  time via ``ApprovalDelegationRepository``; a delegated decision is audited
  with actor type ``delegated`` plus the delegator). Every decision is an
  append-only transition; the instance advances to the next pending step and
  completes (``approved``/``rejected``/``request_changes``) after the final
  step, with the module port notified.

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
from decimal import Decimal
from typing import Any

from core.features.approval_workflow.delegation_repository import ApprovalDelegationRepository
from core.features.approval_workflow.dsl import (
    AmountAtLeastCondition,
    AmountBelowCondition,
    PermissionAssignee,
    RoleAssignee,
    RoutingCondition,
    UserListAssignee,
    WorkflowDefinition,
    WorkflowStep,
)
from core.features.approval_workflow.instance_repository import (
    ApprovalWorkflowInstanceRepository,
)
from core.features.approval_workflow.models.instance import ErpApprovalWorkflowInstanceModel
from core.features.approval_workflow.models.step import ErpApprovalWorkflowStepModel
from core.features.approval_workflow.ports import ApprovalResourcePort
from skyrict_common.exceptions import ConflictError, NotFoundError, PermissionDeniedError

# Statuses the engine owns.
INSTANCE_PENDING = "pending"
INSTANCE_APPROVED = "approved"
INSTANCE_AUTO_APPROVED = "auto_approved"
INSTANCE_REJECTED = "rejected"
INSTANCE_REQUEST_CHANGES = "request_changes"

STEP_PENDING = "pending"
STEP_ESCALATED = "escalated"
STEP_APPROVED = "approved"
STEP_REJECTED = "rejected"

ASSIGNEE_DELIMITER = ","

#: actor types recorded on audit transitions
ACTOR_HUMAN = "human"
ACTOR_SYSTEM = "system"


@dataclass(frozen=True)
class SubmitResult:
    instance: ErpApprovalWorkflowInstanceModel
    steps: list[ErpApprovalWorkflowStepModel]
    auto_approved: bool


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


def _condition_matches(condition: RoutingCondition, amount: Decimal | None) -> bool:
    """Evaluate a DSL routing condition against the submission amount.

    A missing amount never matches (fail closed - auto-approval is opt-in).
    Comparisons use the DSL's exact :class:`Decimal` semantics; floats are
    forbidden for money.
    """
    if amount is None:
        return False
    if isinstance(condition, AmountBelowCondition):
        return amount < condition.amount
    if isinstance(condition, AmountAtLeastCondition):
        return amount >= condition.amount
    raise TypeError(f"unsupported routing condition: {type(condition).__name__}")


class ApprovalEngine:
    """Stateful engine facade over a repository; one engine per request/session."""

    def __init__(
        self,
        repository: ApprovalWorkflowInstanceRepository,
        *,
        now: Callable[[], datetime],
        resource_port: ApprovalResourcePort | None = None,
        delegation_repository: ApprovalDelegationRepository | None = None,
    ) -> None:
        self._repo = repository
        self._now = now
        self._resource_port = resource_port
        self._delegation_repo = delegation_repository

    async def submit(
        self,
        *,
        tenant_id: uuid.UUID,
        definition: WorkflowDefinition,
        definition_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        amount: Decimal | None,
        submitted_by: uuid.UUID,
    ) -> SubmitResult:
        """Create an instance, resolve steps and apply auto-approval routing.

        Steps are resolved in definition order; each step's ``sla`` (when
        present) sets ``sla_due_at = now + hours``. The submission transition
        is recorded with actor type ``system`` (the submitter is captured on
        the instance itself).

        Auto-approval is evaluated against ``amount`` in definition order: a
        matching step is approved by the system actor (audit transition with
        actor type ``system``); the first non-matching step becomes the
        pending queue. When every step auto-approves the instance completes
        as ``auto_approved`` and the module port's ``on_approved`` is called
        with the system actor.
        """
        now = self._now()
        steps: list[dict[str, Any]] = []
        for definition_step in definition.steps:
            kind, value = _assignee_value(definition_step)
            sla_due_at = (
                now + timedelta(hours=definition_step.sla.hours) if definition_step.sla else None
            )
            steps.append(
                {
                    "step_key": definition_step.key,
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

        # Auto-approval routing in definition order.
        first_pending: ErpApprovalWorkflowStepModel | None = None
        for dsl_step, step_row in zip(definition.steps, instance_steps, strict=True):
            if dsl_step.auto_approval is not None and _condition_matches(
                dsl_step.auto_approval.when, amount
            ):
                decided_step = await self._repo.update_step_decision(
                    tenant_id=tenant_id,
                    step_id=step_row.id,
                    status=STEP_APPROVED,
                    decided_by=None,
                    decided_at=now,
                    actor_type=ACTOR_SYSTEM,
                )
                if decided_step is None:
                    raise NotFoundError(f"Step {step_row.id} not found")
                await self._repo.record_transition(
                    tenant_id=tenant_id,
                    workflow_instance_id=instance.id,
                    step_id=decided_step.id,
                    previous_state=STEP_PENDING,
                    new_state="auto_approved",
                    actor_id=None,
                    actor_type=ACTOR_SYSTEM,
                    context={"condition": dsl_step.auto_approval.when.kind},
                    occurred_at=now,
                )
            else:
                first_pending = step_row
                break

        if first_pending is None:
            # Every step auto-approved: complete the instance.
            status = INSTANCE_AUTO_APPROVED
            await self._repo.update_instance_status(
                tenant_id=tenant_id,
                instance_id=instance.id,
                status=status,
                current_step_index=len(instance_steps) - 1,
                updated_by=submitted_by,
                now=now,
            )
            if self._resource_port is not None:
                await self._resource_port.on_approved(
                    tenant_id=tenant_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    decider_actor_type=ACTOR_SYSTEM,
                )
            updated = await self._repo.get_instance(tenant_id, instance.id)
            if updated is None:
                raise NotFoundError(f"Approval instance {instance.id} not found")
            return SubmitResult(instance=updated, steps=list(instance_steps), auto_approved=True)

        # Some steps wait on a human queue: point the instance at the first
        # pending step (skip past auto-approved ones).
        await self._repo.update_instance_status(
            tenant_id=tenant_id,
            instance_id=instance.id,
            status=INSTANCE_PENDING,
            current_step_index=first_pending.step_index,
            updated_by=submitted_by,
            now=now,
        )
        updated = await self._repo.get_instance(tenant_id, instance.id)
        if updated is None:
            raise NotFoundError(f"Approval instance {instance.id} not found")
        return SubmitResult(instance=updated, steps=list(instance_steps), auto_approved=False)

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
        - the target step exists, belongs to the instance, and is ``pending``
          or ``escalated`` (escalation is a supervisory nudge, never a
          decision - an escalated step is still acted on by its assignees);
        - ``actor_id`` is a member of the step's resolved assignee set
          (role members / permission members / explicit user list) or an
          active delegate of such a member (the grant's permission and
          resource_type scopes must match the step and instance; a delegated
          decision records ``actor_type='delegated'`` and the delegator).

        Every decision appends an audit transition with actor type ``human``
        (or ``delegated``) and advances the instance to the next pending step;
        after the final step the instance completes as ``approved`` /
        ``rejected`` / ``request_changes``.
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
        if target.status not in (STEP_PENDING, STEP_ESCALATED):
            raise ConflictError(
                f"Step '{target.step_key}' is {target.status}, not pending or escalated"
            )

        assignee_ids = await self._step_assignee_ids(tenant_id, target)
        delegated_actor: uuid.UUID | None = None
        actor_type = ACTOR_HUMAN

        if actor_id not in assignee_ids and self._delegation_repo is not None:
            # Delegate of an assignee may decide when their grant is active
            # and its scopes match this step and instance (fail closed).
            grants = await self._delegation_repo.list_grants_from_delegators(
                tenant_id=tenant_id,
                delegators=assignee_ids,
                now=now,
            )
            for grant in grants:
                if (
                    grant.resource_type is not None
                    and grant.resource_type != instance.resource_type
                ):
                    continue
                if grant.permission is not None and target.assignee_kind != "permission":
                    continue
                if grant.permission is not None and grant.permission != target.assignee_value:
                    continue
                if grant.delegate == actor_id:
                    delegated_actor = grant.delegator
                    actor_type = "delegated"
                    break

        if actor_id not in assignee_ids and delegated_actor is None:
            raise PermissionDeniedError(
                f"User {actor_id} is not an assignee of step '{target.step_key}'"
            )

        if decision not in (STEP_APPROVED, STEP_REJECTED, "request_changes"):
            raise ConflictError(f"Unsupported decision: {decision!r}")

        step_status = STEP_APPROVED if decision == STEP_APPROVED else STEP_REJECTED
        if decision == "request_changes":
            step_status = "rejected"

        # Audit the REAL previous state: ``update_step_decision`` mutates the
        # identity-mapped step row, so read it before the decision write.
        previous_state = target.status

        step = await self._repo.update_step_decision(
            tenant_id=tenant_id,
            step_id=target.id,
            status=step_status,
            decided_by=actor_id,
            decided_at=now,
            actor_type=actor_type,
            delegated_from=delegated_actor,
        )
        if step is None:
            raise NotFoundError(f"Step {target.id} not found")

        await self._repo.record_transition(
            tenant_id=tenant_id,
            workflow_instance_id=instance_id,
            step_id=step.id,
            previous_state=previous_state,
            new_state=decision,
            actor_id=actor_id,
            actor_type=actor_type,
            reason=reason,
            original_assignee=delegated_actor or actor_id,
            delegated_actor=delegated_actor,
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

        final_status = {
            "approved": INSTANCE_APPROVED,
            "rejected": INSTANCE_REJECTED,
            "request_changes": INSTANCE_REQUEST_CHANGES,
        }[decision]
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
        if self._resource_port is not None:
            if decision == "approved":
                await self._resource_port.on_approved(
                    tenant_id=tenant_id,
                    resource_type=updated.resource_type,
                    resource_id=updated.resource_id,
                    decider_actor_type=actor_type,
                    reason=reason,
                )
            elif decision == "rejected":
                await self._resource_port.on_rejected(
                    tenant_id=tenant_id,
                    resource_type=updated.resource_type,
                    resource_id=updated.resource_id,
                    reason=reason,
                )
            else:
                await self._resource_port.on_request_changes(
                    tenant_id=tenant_id,
                    resource_type=updated.resource_type,
                    resource_id=updated.resource_id,
                    reason=reason,
                )
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
