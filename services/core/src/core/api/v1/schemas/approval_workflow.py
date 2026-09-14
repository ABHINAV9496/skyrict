"""Pydantic request/response schemas for the approval-workflow API (SKY-92).

The inbox API is a read-model over ``ApprovalWorkflowQueryService`` views plus
the decision write through the engine. Every response renders the ORM models
with explicit fields (no raw model serialization), mirroring the payroll and
finance schema contracts. Decision bodies accept ``approve`` / ``reject`` /
``request_changes``; the engine validates the actor against the step's
resolved assignee set at decision time, so the API layer never re-implements
eligibility.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from core.features.approval_workflow.engine import DecisionResult
from core.features.approval_workflow.query import (
    ApprovalInboxEntry,
    ApprovalInstanceView,
    ApprovalStepView,
    ApprovalSuggestionView,
    ApprovalTransitionView,
)

_RESOURCE_LABELS = {
    "journal_entry": "Journal Entry",
    "payroll_run": "Payroll Run",
}


class ApprovalSuggestionOut(BaseModel):
    """The AI routing suggestion surfaced to the reviewer (advisory only)."""

    recommendation: str | None
    confidence: str | None
    reasoning: str | None
    model_used: str | None
    suggested_approver_id: uuid.UUID | None

    @classmethod
    def from_view(cls, view: ApprovalSuggestionView) -> ApprovalSuggestionOut:
        return cls(
            recommendation=view.recommendation,
            confidence=view.confidence,
            reasoning=view.reasoning,
            model_used=view.model_used,
            suggested_approver_id=view.suggested_approver_id,
        )


class ApprovalInboxItemOut(BaseModel):
    """One pending inbox item: the instance context + the current step."""

    instance_id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID
    resource_label: str
    status: str
    submitted_by: uuid.UUID
    submitted_at: datetime
    current_step_index: int
    step_key: str
    step_status: str
    sla_due_at: datetime | None
    eligible_as: str
    delegated_from: uuid.UUID | None
    suggestion: ApprovalSuggestionOut | None

    @classmethod
    def from_entry(cls, entry: ApprovalInboxEntry) -> ApprovalInboxItemOut:
        instance = entry.item.instance
        step = entry.item.step
        return cls(
            instance_id=instance.id,
            resource_type=instance.resource_type,
            resource_id=instance.resource_id,
            resource_label=_RESOURCE_LABELS.get(instance.resource_type, instance.resource_type),
            status=instance.status,
            submitted_by=instance.submitted_by,
            submitted_at=instance.submitted_at,
            current_step_index=instance.current_step_index,
            step_key=step.step_key,
            step_status=step.status,
            sla_due_at=step.sla_due_at,
            eligible_as=entry.item.eligible_as,
            delegated_from=entry.item.delegated_from,
            suggestion=(
                ApprovalSuggestionOut.from_view(entry.suggestion)
                if entry.suggestion is not None
                else None
            ),
        )


class ApprovalStepOut(BaseModel):
    """One step of an instance, including its decision fields."""

    step_index: int
    step_key: str
    assignee_kind: str
    assignee_value: str
    status: str
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    sla_due_at: datetime | None
    delegated_from: uuid.UUID | None

    @classmethod
    def from_step(cls, view: ApprovalStepView) -> ApprovalStepOut:
        return cls(
            step_index=view.step_index,
            step_key=view.step_key,
            assignee_kind=view.assignee_kind,
            assignee_value=view.assignee_value,
            status=view.status,
            decided_by=view.decided_by,
            decided_at=view.decided_at,
            sla_due_at=view.sla_due_at,
            delegated_from=view.delegated_from,
        )


class ApprovalTransitionOut(BaseModel):
    """One append-only audit transition (the instance's decision history)."""

    new_state: str
    previous_state: str | None
    actor_type: str
    actor_id: uuid.UUID | None
    reason: str | None
    step_key: str | None
    occurred_at: datetime | None

    @classmethod
    def from_view(cls, view: ApprovalTransitionView) -> ApprovalTransitionOut:
        return cls(
            new_state=view.new_state,
            previous_state=view.previous_state,
            actor_type=view.actor_type,
            actor_id=view.actor_id,
            reason=view.reason,
            step_key=view.step_key,
            occurred_at=view.occurred_at,
        )


class ApprovalInstanceOut(BaseModel):
    """Full instance detail: header, steps, transitions and the suggestion."""

    instance_id: uuid.UUID
    definition_id: uuid.UUID
    definition_version: int
    resource_type: str
    resource_id: uuid.UUID
    resource_label: str
    status: str
    current_step_index: int
    submitted_by: uuid.UUID
    submitted_at: datetime
    completed_at: datetime | None
    sla_due_at: datetime | None
    suggestion: ApprovalSuggestionOut | None
    steps: list[ApprovalStepOut]
    transitions: list[ApprovalTransitionOut]

    @classmethod
    def from_view(cls, view: ApprovalInstanceView) -> ApprovalInstanceOut:
        instance = view.instance
        return cls(
            instance_id=instance.id,
            definition_id=instance.definition_id,
            definition_version=instance.definition_version,
            resource_type=instance.resource_type,
            resource_id=instance.resource_id,
            resource_label=_RESOURCE_LABELS.get(instance.resource_type, instance.resource_type),
            status=instance.status,
            current_step_index=instance.current_step_index,
            submitted_by=instance.submitted_by,
            submitted_at=instance.submitted_at,
            completed_at=instance.completed_at,
            sla_due_at=instance.sla_due_at,
            suggestion=(
                ApprovalSuggestionOut.from_view(view.suggestion)
                if view.suggestion is not None
                else None
            ),
            steps=[ApprovalStepOut.from_step(step) for step in view.steps],
            transitions=[ApprovalTransitionOut.from_view(t) for t in view.transitions],
        )


class ApprovalDecisionIn(BaseModel):
    """A reviewer's decision on the instance's current step."""

    decision: Literal["approve", "reject", "request_changes"]
    reason: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional note appended to the audit transition",
    )


class ApprovalDecisionOut(BaseModel):
    """The outcome of a decision: the instance + the decided step."""

    instance_id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID
    instance_status: str
    step_key: str
    step_status: str
    instance_completed: bool

    @classmethod
    def from_result(cls, result: DecisionResult) -> ApprovalDecisionOut:
        return cls(
            instance_id=result.instance.id,
            resource_type=result.instance.resource_type,
            resource_id=result.instance.resource_id,
            instance_status=result.instance.status,
            step_key=result.step.step_key,
            step_status=result.step.status,
            instance_completed=result.instance_completed,
        )


__all__ = [
    "ApprovalDecisionIn",
    "ApprovalDecisionOut",
    "ApprovalInboxItemOut",
    "ApprovalInstanceOut",
    "ApprovalStepOut",
    "ApprovalSuggestionOut",
    "ApprovalTransitionOut",
]
