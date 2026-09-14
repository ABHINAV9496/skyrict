"""Payroll run approval coordinator and payroll resource port adapter (SKY-92).

The composition root (``core.api.deps.get_payroll_service``) wires a
``PayrollRunApprovalCoordinator`` onto ``PayrollService.approve_run`` as the
optional ``PayrollRunApprovalPort`` seam. This module implements two
cooperating pieces:

``PayrollApprovalResourcePort`` - the engine-side observer the engine drives
when a submission is auto-approved (or approved by a human). Payroll's
authoritative APPROVED transition stays in ``PayrollService`` via the
``complete_verified`` callback: the adapter never touches audit events or
SQLAlchemy.

``PayrollRunApprovalCoordinator`` - the payroll-service-side orchestrator
that:

1. short-circuits to the direct approve path when the tenant's
   ``payroll_approval_engine`` flag is OFF (no behavioural change);
2. resolves the active workflow definition for ``payroll_run`` and
   ``ApprovalDefinitionMissingError``s when the flag is ON but no definition
   exists (fail safe: never a silent direct approval);
3. submits to the engine; auto-approved runs transition immediately (the
   adapter's ``on_approved`` drives ``PayrollService.complete_approval``);
4. routes at-or-above-threshold amounts onto the human approval queue and
   optionally asks ai-agent for an advisory suggestion (fail-safe degrade).

AI routing: the suggestion is fired after the submission lands on the human
queue; the caller's ``Authorization`` and tenant slug are relayed so
ai-agent re-verifies the JWT and cross-checks the tenant. A broken or absent
AI service never blocks the queue (``ApprovalSuggestionService`` is
fail-safe).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from core.core.exceptions import ApprovalDefinitionMissingError
from core.features.approval_workflow.definition_repository import (
    ApprovalWorkflowDefinitionRepository,
)
from core.features.approval_workflow.delegation_repository import (
    ApprovalDelegationRepository,
)
from core.features.approval_workflow.engine import ApprovalEngine
from core.features.approval_workflow.instance_repository import (
    ApprovalWorkflowInstanceRepository,
)
from core.features.approval_workflow.models.step import ErpApprovalWorkflowStepModel
from core.features.approval_workflow.tenant_flags import payroll_approval_engine_enabled

if TYPE_CHECKING:
    from core.domain.entities import PayrollRun
    from core.features.approval_workflow.ai_routing import ApprovalSuggestionService

RESOURCE_TYPE = "payroll_run"

__all__ = [
    "PayrollApprovalResourcePort",
    "PayrollRunApprovalCoordinator",
]


class PayrollApprovalResourcePort:
    """Engine-side observer: ``on_approved`` triggers the authoritative payroll transition.

    The engine calls this port when a submission is auto-approved (system
    actor) or approved by a human. ``complete_verified`` is a callback bound
    to ``PayrollService.complete_approval`` (the single authority for audit +
    event + repo write). The adapter stores the approved run so the
    coordinator can return it as the authoritative ``PayrollRun`` for the
    HTTP response.
    """

    def __init__(
        self,
        *,
        complete: Callable[..., Any],
        now: Callable[[], datetime],
    ) -> None:
        self._complete = complete
        self._now = now
        self.last_approval: PayrollRun | None = None

    async def submit_for_approval(self, **kwargs: Any) -> None:
        """No-op: the engine instance is the system of record; run stays COMPUTED."""

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
        """Drive the authoritative APPROVED transition into payroll via the callback."""
        self.last_approval = await self._complete(
            tenant_id=tenant_id,
            run_id=resource_id,
            approved_by=decided_by,
            actor_user_id=decided_by,
            approved_at=self._now(),
        )

    async def on_rejected(self, **kwargs: Any) -> None:
        """No-op: run stays COMPUTED."""

    async def on_request_changes(self, **kwargs: Any) -> None:
        """No-op: run stays COMPUTED."""

    async def on_cancelled(self, **kwargs: Any) -> None:
        """No-op: run stays COMPUTED."""


class PayrollRunApprovalCoordinator:
    """Payroll-service-side orchestrator for flag-gated run approval (SKY-92).

    Implements :class:`PayrollRunApprovalPort` so ``PayrollService.approve_run``
    can defer to the approval engine without the service touching SQLAlchemy
    or the approval tables.

    Flag-ON + active definition = engine mandatory; flag-OFF = transparent
    passthrough to the direct approve path (zero behavioural change).
    """

    def __init__(
        self,
        *,
        db: AsyncSession,
        definitions: ApprovalWorkflowDefinitionRepository,
        instances: ApprovalWorkflowInstanceRepository,
        delegations: ApprovalDelegationRepository,
        now: Callable[[], datetime],
        ai_client: httpx.AsyncClient | None,
        ai_authorization: str | None,
        ai_tenant_slug: str | None,
        complete_verified: Callable[..., Awaitable[PayrollRun]],
        suggestion_service: ApprovalSuggestionService | None = None,
    ) -> None:
        self._db = db
        self._definitions = definitions
        self._instances = instances
        self._delegations = delegations
        self._now = now
        self._ai_client = ai_client
        self._ai_authorization = ai_authorization
        self._ai_tenant_slug = ai_tenant_slug
        self._complete_verified = complete_verified
        self._suggestion_service = suggestion_service

    # ------------------------------------------------------------------
    # PayrollRunApprovalPort
    # ------------------------------------------------------------------

    async def submit_for_approval(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        run: PayrollRun,
        total_net: Decimal,
        actor_user_id: uuid.UUID | None = None,
    ) -> PayrollRun:
        """Route payroll run approval through the approval engine.

        Flag OFF: direct APPROVED transition (identical to the pre-engine
        path). Flag ON: engine mandatory. Missing active definition is a
        controlled config error (``ApprovalDefinitionMissingError``); the run
        stays COMPUTED and never falls back to a direct approval.

        Auto-approved amounts (below the definition's threshold) transition
        immediately via the payroll resource port (``actor_type='system'``
        audit + payroll event). At-or-above-threshold amounts land on the
        human approval queue; the run is returned unchanged (still COMPUTED).
        """
        # The run always comes from a repository lookup with a materialized
        # id; the entity keeps it optional only for the construct-then-persist
        # flow.
        assert run.id is not None

        if not await payroll_approval_engine_enabled(self._db, tenant_id):
            return await self._complete_verified(
                tenant_id=tenant_id,
                run_id=run.id,
                approved_by=user_id,
                actor_user_id=actor_user_id,
                approved_at=self._now(),
            )

        active = await self._definitions.get_active(tenant_id, RESOURCE_TYPE)
        if active is None:
            raise ApprovalDefinitionMissingError(
                "The payroll approval engine is enabled but no active "
                "definition was seeded for this tenant"
            )

        from core.features.approval_workflow.dsl import WorkflowDefinition

        definition = WorkflowDefinition.model_validate(active.definition)

        port = PayrollApprovalResourcePort(complete=self._complete_verified, now=self._now)
        engine = ApprovalEngine(
            repository=self._instances,
            now=self._now,
            resource_port=port,
            delegation_repository=self._delegations,
        )
        result = await engine.submit(
            tenant_id=tenant_id,
            definition=definition,
            definition_id=active.id,
            resource_type=RESOURCE_TYPE,
            resource_id=run.id,  # guaranteed materialized above
            amount=total_net,
            submitted_by=user_id,
        )

        if result.auto_approved:
            assert port.last_approval is not None, (
                "engine reported auto_approved but PayrollApprovalResourcePort "
                "on_approved was not called"
            )
            return port.last_approval

        # Human queue: fire advisory AI suggestion when the pending step is
        # AI-assisted (fail-safe: never blocks).
        from core.features.approval_workflow.ai_routing import (
            ApprovalSuggestionService,
        )
        from core.features.approval_workflow.dsl import RoutingStrategy

        pending_step = result.steps[result.instance.current_step_index]
        step_def = definition.steps[result.instance.current_step_index]
        if step_def.routing == RoutingStrategy.AI_ASSISTED:
            suggestion_svc = self._suggestion_service or ApprovalSuggestionService(
                repository=self._instances,
                now=self._now,
            )
            eligible = await self._eligible_approvers(tenant_id, pending_step)
            description = f"payroll run {run.run_code}"
            await suggestion_svc.suggest_and_record(
                client=self._ai_client,
                authorization=self._ai_authorization,
                tenant_slug=self._ai_tenant_slug,
                tenant_id=tenant_id,
                instance=result.instance,
                step=pending_step,
                amount=total_net,
                description=description,
                allowed_approver_ids=set(eligible) if eligible else None,
            )

        # Run stays COMPUTED; approval happens via decide() later.
        return run

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _eligible_approvers(
        self, tenant_id: uuid.UUID, step: ErpApprovalWorkflowStepModel
    ) -> list[uuid.UUID]:
        """Resolve the step's assignee set for AI-suggestion validation.

        Mirrors ``ApprovalEngine._step_assignee_ids`` to keep the validation
        set consistent without importing the engine's private method.
        """
        if step.assignee_kind == "role":
            return await self._instances.resolve_role_members(tenant_id, step.assignee_value)
        if step.assignee_kind == "permission":
            return await self._instances.resolve_permission_members(tenant_id, step.assignee_value)
        if step.assignee_kind == "users":
            return [uuid.UUID(part) for part in step.assignee_value.split(",") if part]
        return []
