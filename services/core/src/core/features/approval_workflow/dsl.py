"""Approval workflow DSL (SKY-92) - versioned, Pydantic-validated definitions.

Workflow definitions are Pydantic v2 models serialized as JSONB documents and
stored per tenant with an integer version. A version becomes immutable once it
is activated (the storage layer rejects updates to active versions; a new
definition version is created instead).

The DSL is deliberately generic - the engine never interprets "journal entry"
or "payroll run" semantics:

- ``resource_type`` is a plain string carried by the definition; modules bind
  their resources to a type when they submit them.
- Assignee conditions are role / permission / explicit user-list. "CFO" is a
  business configuration concern: a tenant models it as the role or permission
  that identifies its finance approver queue, never as an engine concept.
- Amount thresholds are ``Decimal`` (19,4) and are compared exactly - floats
  are forbidden for money (repo convention).
- ``routing`` is advisory: ``ai_assisted`` asks the AI service for an approver
  suggestion that the engine validates against the step's hard constraints and
  falls back to deterministic routing when the service is unavailable.
- Delegation is runtime state, never part of a definition (``delegation_allowed``
  only controls whether a step may be delegated at all).

Serialization note: amounts must round-trip through JSON exactly, so definitions
are written with ``model_dump(mode="json")`` (pydantic v2 serializes ``Decimal``
as an exact string) and read back with ``model_validate``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RoutingStrategy(StrEnum):
    """How a step's assignee is chosen.

    ``deterministic`` resolves the assignee from the step's assignee condition.
    ``ai_assisted`` additionally asks the AI service for a suggestion and only
    accepts it after the engine validates tenant membership, permission, role /
    user-list eligibility and resource access. On AI unavailability the engine
    falls back to deterministic routing - it never skips an approval.
    """

    DETERMINISTIC = "deterministic"
    AI_ASSISTED = "ai_assisted"


# ---------------------------------------------------------------------------
# Assignee conditions (discriminated union on ``kind``)
# ---------------------------------------------------------------------------


class RoleAssignee(BaseModel):
    """Route to every user holding the named role."""

    kind: Literal["role"] = "role"
    role: str = Field(
        ..., min_length=1, max_length=100, description="Role name, e.g. finance_manager"
    )


class PermissionAssignee(BaseModel):
    """Route to every user granted the named permission."""

    kind: Literal["permission"] = "permission"
    permission: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="RBAC permission key, e.g. erp.finance.approve",
    )


class UserListAssignee(BaseModel):
    """Route to an explicit list of users (identity users; no FK - identity owns users)."""

    kind: Literal["users"] = "users"
    user_ids: list[uuid.UUID] = Field(..., min_length=1)


AssigneeSpec = Annotated[
    RoleAssignee | PermissionAssignee | UserListAssignee, Field(discriminator="kind")
]


# ---------------------------------------------------------------------------
# Routing conditions (evaluated by the engine against a resource amount)
# ---------------------------------------------------------------------------


class AmountBelowCondition(BaseModel):
    """True when the resource amount is strictly below ``amount`` (exact Decimal compare)."""

    kind: Literal["amount_below"] = "amount_below"
    amount: Decimal = Field(
        ...,
        gt=0,
        decimal_places=4,
        description="Exclusive upper bound; Decimal(19,4) compared exactly, never float",
    )


class AmountAtLeastCondition(BaseModel):
    """True when the resource amount is greater than or equal to ``amount``."""

    kind: Literal["amount_at_least"] = "amount_at_least"
    amount: Decimal = Field(..., gt=0, decimal_places=4)


RoutingCondition = Annotated[
    AmountBelowCondition | AmountAtLeastCondition, Field(discriminator="kind")
]


class AutoApprovalRule(BaseModel):
    """Auto-approve the step (system/automation actor) when ``when`` matches.

    The engine still records a full audit transition with actor type ``system``
    and still drives the module's authoritative state transition through its
    resource port. A human is never substituted for the automation actor.
    """

    when: RoutingCondition


# ---------------------------------------------------------------------------
# SLA / escalation
# ---------------------------------------------------------------------------


class EscalationPolicy(BaseModel):
    """What happens at SLA breach: reassign to ``assignee`` with an audit transition."""

    assignee: AssigneeSpec


class SlaPolicy(BaseModel):
    """Step service-level agreement: breach at ``hours``, reminder at ``hours - reminder_before_hours``."""

    hours: int = Field(..., gt=0, description="Step SLA in hours; breach at this point")
    reminder_before_hours: int = Field(
        default=1, gt=0, description="Reminder lead in hours; must be less than ``hours``"
    )
    escalation: EscalationPolicy | None = Field(
        default=None, description="Reassignment target on SLA breach; None = no auto-escalation"
    )

    @model_validator(mode="after")
    def _reminder_must_precede_sla(self) -> SlaPolicy:
        if self.reminder_before_hours >= self.hours:
            raise ValueError(
                "reminder_before_hours must be less than sla hours "
                f"(got reminder={self.reminder_before_hours}, sla={self.hours})"
            )
        return self


# ---------------------------------------------------------------------------
# Definition
# ---------------------------------------------------------------------------


class WorkflowStep(BaseModel):
    """One step of an approval chain.

    ``key`` identifies the step for history/audit references. ``assignee`` is the
    routing target; ``routing`` chooses deterministic vs AI-assisted selection.
    ``auto_approval``, when present and matching, lets the engine complete the
    step without a human actor. ``sla`` governs reminders and breach escalation.
    ``delegation_allowed`` controls runtime approver-level delegation.
    """

    key: str = Field(..., min_length=1, max_length=100)
    assignee: AssigneeSpec
    routing: RoutingStrategy = RoutingStrategy.DETERMINISTIC
    auto_approval: AutoApprovalRule | None = None
    sla: SlaPolicy | None = None
    delegation_allowed: bool = True


class WorkflowDefinition(BaseModel):
    """A versioned, per-tenant approval workflow definition (JSONB document)."""

    name: str = Field(..., min_length=1, max_length=255)
    resource_type: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Generic resource type key, e.g. journal_entry",
    )
    version: int = Field(
        ..., ge=1, description="Definition version; unique per (tenant, resource_type)"
    )
    steps: list[WorkflowStep] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _step_keys_must_be_unique(self) -> WorkflowDefinition:
        seen: set[str] = set()
        for step in self.steps:
            if step.key in seen:
                raise ValueError(f"duplicate step key: {step.key!r}")
            seen.add(step.key)
        return self
