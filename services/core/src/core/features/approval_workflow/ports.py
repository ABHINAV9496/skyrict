"""Approval workflow resource ports (SKY-92, routing/auto-approve commit).

The engine is resource-agnostic; modules observe approval outcomes through a
resource port the engine calls when a submission needs the module's
authoritative state transition:

- ``submit_for_approval`` - the module records that its resource entered the
  approval pipeline (the engine instance is the system of record for the
  workflow; the module keeps its own "pending approval" marker).
- ``on_approved`` - the module drives its authoritative transition to the
  approved state (finance posts a drafted journal entry; payroll approves a
  computed run). ``decider_actor_type`` distinguishes the *system* (auto
  approval / worker) from a human approver, mirroring the audit transition.
- ``on_rejected`` / ``on_request_changes`` - the module resets to its
  pre-approval state (draft / computed) with the reviewer's reason.
- ``on_cancelled`` - a submitted resource is released without a decision.

A module never imports the engine: the composition root injects an
implementation of :class:`ApprovalResourcePort` into the wiring seam, exactly
like payroll's ``PayslipApprovedNotifierPort``.
"""

from __future__ import annotations

import uuid
from typing import Protocol


class ApprovalResourcePort(Protocol):
    """Cross-feature contract implemented by finance, payroll, etc."""

    async def submit_for_approval(
        self,
        *,
        tenant_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        submitted_by: uuid.UUID,
    ) -> None:
        """Record the module-side 'pending approval' state for a resource."""
        ...

    async def on_approved(
        self,
        *,
        tenant_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        decider_actor_type: str,
        reason: str | None = None,
        decided_by: uuid.UUID | None = None,
    ) -> None:
        """Apply the approved state to the module's resource (authoritative).

        ``decided_by`` is the approving user when a human decided (``None``
        for system auto-approval); modules use it for attribution on the
        resource state change (e.g. ``posted_by_user_id``).
        """
        ...

    async def on_rejected(
        self,
        *,
        tenant_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        reason: str | None = None,
    ) -> None:
        """Revert the module's resource to its pre-approval state."""
        ...

    async def on_request_changes(
        self,
        *,
        tenant_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        reason: str | None = None,
    ) -> None:
        """Return the resource to draft with the reviewer's change request."""
        ...

    async def on_cancelled(
        self,
        *,
        tenant_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        reason: str | None = None,
    ) -> None:
        """Release a submitted resource without a decision."""
        ...


__all__ = ["ApprovalResourcePort"]
