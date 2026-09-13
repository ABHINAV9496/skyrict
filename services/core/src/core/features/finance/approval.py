"""Journal-entry approval coordinator and finance resource port adapter (SKY-92).

The composition root (``core.api.deps.get_finance_service``) wires a
``JournalEntryApprovalCoordinator`` onto ``FinanceService.post_journal_entry``
as the optional ``JournalEntryApprovalPort`` seam. This module implements two
cooperating pieces:

``FinanceApprovalResourcePort`` - the engine-side observer the engine drives
when a submission is auto-approved (or approved by a human). Finance's
authoritative posting stays in ``FinanceService`` via the ``post_verified``
callback: the adapter never touches audit events or SQLAlchemy.

``JournalEntryApprovalCoordinator`` - the finance-service-side orchestrator
that:

1. short-circuits to the direct post path when the tenant's
   ``je_approval_engine`` flag is OFF (no behavioural change);
2. resolves the active workflow definition for ``journal_entry`` and
   ``ApprovalDefinitionMissingError``s when the flag is ON but no
   definition exists (fail safe: never a silent direct post);
3. submits to the engine; auto-approved entries post immediately (the
   adapter's ``on_approved`` drives ``FinanceService.complete_posting``);
4. routes at-or-above-threshold amounts onto the human approval queue and
   optionally asks ai-agent for an advisory suggestion (fail-safe degrade).

AI routing: the suggestion is fired after the submission lands on the human
queue; the caller's ``Authorization`` and tenant slug are relayed so
ai-agent re-verifies the JWT and cross-checks the tenant. A broken or
absent AI service never blocks the queue (``ApprovalSuggestionService`` is
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
from core.features.approval_workflow.tenant_flags import je_approval_engine_enabled

if TYPE_CHECKING:
    from core.domain.entities import JournalEntry
    from core.features.approval_workflow.ai_routing import ApprovalSuggestionService

RESOURCE_TYPE = "journal_entry"

__all__ = [
    "FinanceApprovalResourcePort",
    "JournalEntryApprovalCoordinator",
]


class FinanceApprovalResourcePort:
    """Engine-side observer: ``on_approved`` triggers the authoritative finance post.

    The engine calls this port when a submission is auto-approved (system
    actor) or approved by a human. ``post_verified`` is a callback bound to
    ``FinanceService.complete_posting`` (the single authority for audit +
    event + repo write). The adapter stores the posted entry so the
    coordinator can return it as the authoritative ``JournalEntry`` for the
    HTTP response.
    """

    def __init__(
        self,
        *,
        post: Callable[..., Any],
        now: Callable[[], datetime],
    ) -> None:
        self._post = post
        self._now = now
        self.last_posting: JournalEntry | None = None

    async def submit_for_approval(self, **kwargs: Any) -> None:
        """No-op: the engine instance is the system of record; JE stays DRAFT."""

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
        """Drive the authoritative post into finance via the callback."""
        self.last_posting = await self._post(
            tenant_id=tenant_id,
            user_id=decided_by,
            entry_id=resource_id,
            posted_at=self._now(),
        )

    async def on_rejected(self, **kwargs: Any) -> None:
        """No-op: JE stays DRAFT."""

    async def on_request_changes(self, **kwargs: Any) -> None:
        """No-op: JE stays DRAFT."""

    async def on_cancelled(self, **kwargs: Any) -> None:
        """No-op: JE stays DRAFT."""


class JournalEntryApprovalCoordinator:
    """Finance-service-side orchestrator for flag-gated JE approval (SKY-92).

    Implements :class:`JournalEntryApprovalPort` so
    ``FinanceService.post_journal_entry`` can defer to the approval engine
    without the service touching SQLAlchemy or the approval tables.

    Flag-ON + active definition = engine mandatory; flag-OFF = transparent
    passthrough to the direct post path (zero behavioural change).
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
        post_verified: Callable[..., Awaitable[JournalEntry]],
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
        self._post_verified = post_verified
        self._suggestion_service = suggestion_service

    # ------------------------------------------------------------------
    # JournalEntryApprovalPort
    # ------------------------------------------------------------------

    async def submit_for_posting(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        entry: JournalEntry,
        debit_total: Decimal,
    ) -> JournalEntry:
        """Route journal-entry posting through the approval engine.

        Flag OFF: direct post (identical to the pre-engine path).
        Flag ON: engine mandatory. Missing active definition is a controlled
        config error (``ApprovalDefinitionMissingError``); the JE stays
        pre-posting and never falls back to a direct post.

        Auto-approved amounts (below the definition's threshold) post
        immediately via the finance resource port (``actor_type='system'``
        audit + finance event). At-or-above-threshold amounts land on the
        human approval queue; the entry is returned unchanged (still DRAFT).
        """
        # The entry always comes from a repository lookup with a materialized
        # id; the entity keeps it optional only for the construct-then-persist
        # flow.
        assert entry.id is not None

        if not await je_approval_engine_enabled(self._db, tenant_id):
            return await self._post_verified(
                tenant_id=tenant_id,
                user_id=user_id,
                entry_id=entry.id,
                posted_at=self._now(),
            )

        active = await self._definitions.get_active(tenant_id, RESOURCE_TYPE)
        if active is None:
            raise ApprovalDefinitionMissingError(
                "The journal-entry approval engine is enabled but no active "
                "definition was seeded for this tenant"
            )

        from core.features.approval_workflow.dsl import WorkflowDefinition

        definition = WorkflowDefinition.model_validate(active.definition)

        port = FinanceApprovalResourcePort(post=self._post_verified, now=self._now)
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
            resource_id=entry.id,  # guaranteed materialized above
            amount=debit_total,
            submitted_by=user_id,
        )

        if result.auto_approved:
            assert port.last_posting is not None, (
                "engine reported auto_approved but FinanceApprovalResourcePort "
                "on_approved was not called"
            )
            return port.last_posting

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
            description = f"journal entry {entry.memo}" if entry.memo else "journal entry"
            await suggestion_svc.suggest_and_record(
                client=self._ai_client,
                authorization=self._ai_authorization,
                tenant_slug=self._ai_tenant_slug,
                tenant_id=tenant_id,
                instance=result.instance,
                step=pending_step,
                amount=debit_total,
                description=description,
                allowed_approver_ids=set(eligible) if eligible else None,
            )

        # Entry stays DRAFT; approval happens via decide() later.
        return entry

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
