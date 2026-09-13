"""Approval workflow query service - API-facing reads for the SKY-92 inbox.

The engine owns writes; this service owns the read model the API surfaces:

- the user's pending inbox (eligibility resolved live by
  ``ApprovalWorkflowInboxRepository`` against DB RBAC membership + active
  delegations);
- instance detail with every step and every append-only audit transition;
- the latest AI routing suggestion (recorded by ``ApprovalSuggestionService``
  on the ``suggestion`` transition) so the UI can surface it as advisory
  information - never as a decision.

The suggestion is a view over the audited transition context, so the API
never re-computes AI output and the surfaced values are exactly the ones that
passed the ai-agent transport + authorized-approver filtering at submission
time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.features.approval_workflow.inbox_repository import (
    ApprovalWorkflowInboxRepository,
    InboxItem,
)
from core.features.approval_workflow.instance_repository import (
    ApprovalWorkflowInstanceRepository,
)
from core.features.approval_workflow.models.instance import ErpApprovalWorkflowInstanceModel
from core.features.approval_workflow.models.step import ErpApprovalWorkflowStepModel


@dataclass(frozen=True)
class ApprovalSuggestionView:
    """The AI routing suggestion surfaced to the reviewer (advisory only)."""

    recommendation: str | None
    confidence: str | None
    reasoning: str | None
    model_used: str | None
    suggested_approver_id: uuid.UUID | None


@dataclass(frozen=True)
class ApprovalInboxEntry:
    """One pending inbox item plus its (optional) AI suggestion."""

    item: InboxItem
    suggestion: ApprovalSuggestionView | None


@dataclass(frozen=True)
class ApprovalStepView:
    """A step plus its decision fields, as the API renders it."""

    step_index: int
    step_key: str
    assignee_kind: str
    assignee_value: str
    status: str
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    sla_due_at: datetime | None
    delegated_from: uuid.UUID | None


@dataclass(frozen=True)
class ApprovalTransitionView:
    """One append-only audit transition with its step key resolved."""

    new_state: str
    previous_state: str | None
    actor_type: str
    actor_id: uuid.UUID | None
    reason: str | None
    step_key: str | None
    occurred_at: datetime | None


@dataclass(frozen=True)
class ApprovalInstanceView:
    """An instance, its steps, all audit transitions, and the latest suggestion."""

    instance: ErpApprovalWorkflowInstanceModel
    steps: tuple[ApprovalStepView, ...]
    transitions: tuple[ApprovalTransitionView, ...]
    suggestion: ApprovalSuggestionView | None


class ApprovalWorkflowQueryService:
    """API-facing reads over the approval engine's persistence layer."""

    def __init__(
        self,
        *,
        inbox: ApprovalWorkflowInboxRepository,
        instances: ApprovalWorkflowInstanceRepository,
    ) -> None:
        self._inbox = inbox
        self._instances = instances

    async def list_inbox(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        now: datetime,
        limit: int = 100,
    ) -> list[ApprovalInboxEntry]:
        """Pending steps the user may act on, each with its latest suggestion."""
        items = await self._inbox.list_pending_for_user(
            tenant_id=tenant_id,
            user_id=user_id,
            now=now,
            limit=limit,
        )
        entries: list[ApprovalInboxEntry] = []
        for item in items:
            entries.append(
                ApprovalInboxEntry(
                    item=item,
                    suggestion=await self._latest_suggestion(tenant_id, item.instance.id),
                )
            )
        return entries

    async def get_instance(
        self,
        *,
        tenant_id: uuid.UUID,
        instance_id: uuid.UUID,
    ) -> ApprovalInstanceView | None:
        """Instance detail: every step + every audit transition + the suggestion."""
        instance = await self._instances.get_instance(tenant_id, instance_id)
        if instance is None:
            return None

        raw_steps = await self._instances.list_steps(tenant_id, instance_id)
        steps_by_id = {step.id: step for step in raw_steps}
        steps = tuple(self._step_view(step) for step in raw_steps)

        transitions = tuple(
            ApprovalTransitionView(
                new_state=transition.new_state,
                previous_state=transition.previous_state,
                actor_type=transition.actor_type,
                actor_id=transition.actor_id,
                reason=transition.reason,
                step_key=(
                    steps_by_id[transition.step_id].step_key
                    if transition.step_id is not None and transition.step_id in steps_by_id
                    else None
                ),
                occurred_at=transition.occurred_at,
            )
            for transition in await self._instances.list_transitions(tenant_id, instance_id)
        )

        return ApprovalInstanceView(
            instance=instance,
            steps=steps,
            transitions=transitions,
            suggestion=await self._latest_suggestion(tenant_id, instance_id),
        )

    @staticmethod
    def _step_view(step: ErpApprovalWorkflowStepModel) -> ApprovalStepView:
        return ApprovalStepView(
            step_index=step.step_index,
            step_key=step.step_key,
            assignee_kind=step.assignee_kind,
            assignee_value=step.assignee_value,
            status=step.status,
            decided_by=step.decided_by,
            decided_at=step.decided_at,
            sla_due_at=step.sla_due_at,
            delegated_from=step.delegated_from,
        )

    async def _latest_suggestion(
        self, tenant_id: uuid.UUID, instance_id: uuid.UUID
    ) -> ApprovalSuggestionView | None:
        transitions = await self._instances.list_transitions(tenant_id, instance_id)
        for transition in reversed(transitions):
            if transition.actor_type != "ai_suggestion":
                continue
            context: dict[str, Any] = transition.context or {}
            raw_approver = context.get("suggested_approver_id")
            try:
                suggested_approver_id = uuid.UUID(raw_approver) if raw_approver else None
            except (TypeError, ValueError):
                suggested_approver_id = None
            return ApprovalSuggestionView(
                recommendation=context.get("recommendation"),
                confidence=context.get("confidence"),
                reasoning=context.get("reasoning"),
                model_used=context.get("model_used"),
                suggested_approver_id=suggested_approver_id,
            )
        return None


__all__ = [
    "ApprovalInboxEntry",
    "ApprovalInstanceView",
    "ApprovalSuggestionView",
    "ApprovalTransitionView",
    "ApprovalWorkflowQueryService",
]
