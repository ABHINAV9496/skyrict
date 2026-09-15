"""SLA escalation service (SKY-92, escalation commit).

Escalation is a *supervisory nudge, never a decision*: when a pending
instance's current step has an ``sla_due_at`` that has passed, the service
marks that step ``escalated`` and appends an audit transition with actor type
``escalation`` (no actor id - no human or system actor made a decision). The
instance stays ``pending`` and the step remains decidable by its assignees, so
the workflow is never auto-rejected by a missed SLA. The escalation state is
visible in the inbox / detail APIs so approvers can see what is overdue.

Idempotency: only a ``pending`` step can be escalated (the repository filter
is idempotent), and a fresh run never re-escalates the same step. The pass is
bounded by ``limit`` (most-overdue first) so a backlog drains across passes
without one oversized transaction.

The service takes an injectable ``now`` clock (same convention as the engine)
so SLA checks and audit timestamps are deterministic in tests.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from core.features.approval_workflow.instance_repository import (
    ApprovalWorkflowInstanceRepository,
)

ESCALATION_ACTOR = "escalation"


class ApprovalEscalationService:
    """Escalate the overdue current steps of a tenant's pending instances."""

    def __init__(
        self,
        repository: ApprovalWorkflowInstanceRepository,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repo = repository
        self._now = now or (lambda: datetime.now(UTC))

    async def escalate_overdue(
        self,
        *,
        tenant_id: uuid.UUID,
        limit: int = 200,
    ) -> int:
        """Escalate up to ``limit`` overdue pending steps; returns how many.

        Each escalated step gets an append-only transition
        ``pending -> escalated`` (actor type ``escalation``, no actor id)
        carrying the breached SLA due time in the transition context.
        """
        now = self._now()
        steps = await self._repo.list_overdue_steps(
            tenant_id=tenant_id,
            now=now,
            limit=limit,
        )
        escalated = 0
        for step in steps:
            updated = await self._repo.mark_step_escalated(
                tenant_id=tenant_id,
                step_id=step.id,
            )
            if updated is None:
                # A concurrent escalation or decision already handled this
                # step. Skip the transition to avoid double-logging.
                continue
            await self._repo.record_transition(
                tenant_id=tenant_id,
                workflow_instance_id=step.instance_id,
                step_id=step.id,
                previous_state="pending",
                new_state="escalated",
                actor_type=ESCALATION_ACTOR,
                actor_id=None,
                context={"sla_due_at": str(step.sla_due_at)},
                occurred_at=now,
            )
            escalated += 1
        return escalated


__all__ = ["ApprovalEscalationService"]
