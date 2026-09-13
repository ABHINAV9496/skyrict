"""AI routing suggestions for approval workflows (SKY-92, AI-routing commit).

Mirrors ``core.features.finance.ai_suggester``: the module relays a minimal
resource context (resource type/id, routing amount, description) to ai-agent
``POST /api/v1/ai/approval/routing-suggest``. The caller's ``Authorization``
and tenant slug are relayed so ai-agent re-verifies the JWT and cross-checks
the tenant.

An approval suggestion is NEVER an authority: it never changes a step or
instance state. It is advisory context the approver can see in the inbox
(and audit can replay). The audit records it as a transition with actor type
``ai_suggestion`` (see :mod:`...models.transition`); the engine's decision
state machine is untouched.

Failure posture (fail-safe, "never break submission"):

- ``request_approval_routing_suggestion`` surfaces transport and upstream
  failures as :class:`AiServiceUnavailableError` so strict callers can react;
- :class:`ApprovalSuggestionService.suggest_and_record` swallows that error
  and returns ``None`` (no audit row) - a broken AI service must never block
  the human approval queue;
- a missing/no-match upstream payload is an abstention (``None``), same
  degradation path.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from core.core.exceptions import AiServiceUnavailableError
from core.features.ai.proxy import forward_to_ai_agent
from core.features.approval_workflow.instance_repository import (
    ApprovalWorkflowInstanceRepository,
)
from core.features.approval_workflow.models.instance import ErpApprovalWorkflowInstanceModel
from core.features.approval_workflow.models.step import ErpApprovalWorkflowStepModel

_UPSTREAM_PATH = "/api/v1/ai/approval/routing-suggest"

#: the only recommendations the UI-facing type accepts; anything else abstains
_KNOWN_RECOMMENDATIONS = ("approve", "reject", "request_changes")


@dataclass(frozen=True)
class ApprovalRoutingSuggestion:
    """Advisory AI recommendation for the current step (never authority).

    ``recommendation`` is ``None`` when the model abstains; ``confidence`` is
    ``None`` when missing or out of ``[0, 1]`` (fail closed). ``reasoning`` /
    ``model_used`` default to empty strings so the inbox renders cleanly.
    ``suggested_approver_id`` is an OPTIONAL person the model thinks fits the
    step; Core validates it against the step's eligible set before it is ever
    recorded (``None`` when the upstream did not suggest anyone, or when the
    suggested person is not eligible).
    """

    recommendation: str | None
    confidence: Decimal | None
    reasoning: str = ""
    model_used: str = ""
    suggested_approver_id: uuid.UUID | None = None


async def request_approval_routing_suggestion(
    client: httpx.AsyncClient,
    *,
    authorization: str | None,
    tenant_slug: str | None,
    resource_type: str,
    resource_id: uuid.UUID,
    amount: Decimal | None,
    description: str,
) -> ApprovalRoutingSuggestion | None:
    """Ask ai-agent for an advisory routing suggestion; ``None`` on abstention.

    Raises:
        AiServiceUnavailableError: On transport failures, upstream HTTP errors
            (>= 400), or a non-JSON upstream body. Upstream application errors
            are treated as a missing service, never as a decision.
    """
    payload = {
        "resource_type": resource_type,
        "resource_id": str(resource_id),
        "amount": str(amount) if amount is not None else None,
        "description": description,
    }
    upstream = await forward_to_ai_agent(
        client,
        method="POST",
        upstream_path=_UPSTREAM_PATH,
        authorization=authorization,
        tenant_slug=tenant_slug,
        body=json.dumps(payload).encode("utf-8"),
    )
    if upstream.status_code >= 400:
        raise AiServiceUnavailableError("AI approval routing suggestion failed")

    try:
        data = upstream.json()
    except ValueError:
        raise AiServiceUnavailableError(
            "AI approval routing suggestion returned invalid JSON"
        ) from None
    if not isinstance(data, dict):
        raise AiServiceUnavailableError(
            "AI approval routing suggestion returned a non-object body"
        ) from None

    raw_recommendation = str(data.get("recommendation") or "").strip().lower()
    recommendation = raw_recommendation if raw_recommendation in _KNOWN_RECOMMENDATIONS else None

    # Confidence is only meaningful for a recognised recommendation; an
    # abstention never carries one (fail closed).
    confidence: Decimal | None = None
    raw_confidence = data.get("confidence")
    if (
        recommendation is not None
        and isinstance(raw_confidence, (int, float))
        and 0 <= raw_confidence <= 1
    ):
        confidence = Decimal(str(raw_confidence))

    reasoning = str(data.get("reasoning") or "").strip()
    model_used = str(data.get("model_used") or "").strip()

    # The suggested approver is optional and advisory; an unparsable id is an
    # abstention on that field only (never a transport failure).
    suggested_approver_id: uuid.UUID | None = None
    raw_suggested = data.get("suggested_approver_id")
    if isinstance(raw_suggested, str) and raw_suggested.strip():
        try:
            suggested_approver_id = uuid.UUID(raw_suggested.strip())
        except ValueError:
            suggested_approver_id = None

    if recommendation is None and not reasoning and not model_used:
        return None
    return ApprovalRoutingSuggestion(
        recommendation=recommendation,
        confidence=confidence,
        reasoning=reasoning,
        model_used=model_used,
        suggested_approver_id=suggested_approver_id,
    )


def _suggestion_context(suggestion: ApprovalRoutingSuggestion) -> dict[str, Any]:
    """The audit envelope stored on the ``ai_suggestion`` transition."""
    return {
        "recommendation": suggestion.recommendation,
        "confidence": (str(suggestion.confidence) if suggestion.confidence is not None else None),
        "reasoning": suggestion.reasoning,
        "model_used": suggestion.model_used,
        "suggested_approver_id": (
            str(suggestion.suggested_approver_id)
            if suggestion.suggested_approver_id is not None
            else None
        ),
    }


class ApprovalSuggestionService:
    """Ask ai-agent for a routing suggestion and audit it (never a decision).

    The composition root (finance/payroll wiring) calls
    :meth:`suggest_and_record` right after a submission lands on a human
    queue. A failed or missing AI service degrades to ``None`` - the approval
    still proceeds through the normal human path.
    """

    def __init__(
        self,
        *,
        repository: ApprovalWorkflowInstanceRepository,
        now: Callable[[], datetime],
    ) -> None:
        self._repo = repository
        self._now = now

    async def suggest_and_record(
        self,
        *,
        client: httpx.AsyncClient | None,
        authorization: str | None,
        tenant_slug: str | None,
        tenant_id: uuid.UUID,
        instance: ErpApprovalWorkflowInstanceModel,
        step: ErpApprovalWorkflowStepModel,
        amount: Decimal | None,
        description: str,
        allowed_approver_ids: set[uuid.UUID] | None = None,
    ) -> ApprovalRoutingSuggestion | None:
        """Request a suggestion and append its audit transition.

        ``client`` is ``None`` when the feature is not wired (per-tenant flag
        off), which short-circuits to ``None`` without an audit row. Transport
        failures are swallowed (fail-safe); an upstream abstention returns
        ``None`` without an audit row.

        ``allowed_approver_ids`` is the step's eligible approver set
        (resolved by Core from the assignee spec AT THE TIME OF SUBMISSION).
        When the upstream suggests an approver outside that set the suggestion
        is stripped of the person (never recorded, never surfaced) while the
        rest of the recommendation survives - the AI never gets to select an
        unauthorized user.
        """
        if client is None:
            return None
        try:
            suggestion = await request_approval_routing_suggestion(
                client,
                authorization=authorization,
                tenant_slug=tenant_slug,
                resource_type=instance.resource_type,
                resource_id=instance.resource_id,
                amount=amount,
                description=description,
            )
        except AiServiceUnavailableError:
            return None
        if suggestion is None:
            return None
        if (
            suggestion.suggested_approver_id is not None
            and allowed_approver_ids is not None
            and suggestion.suggested_approver_id not in allowed_approver_ids
        ):
            suggestion = dataclasses.replace(suggestion, suggested_approver_id=None)
        await self._repo.record_transition(
            tenant_id=tenant_id,
            workflow_instance_id=instance.id,
            step_id=step.id,
            previous_state=step.status,
            new_state="suggestion",
            actor_type="ai_suggestion",
            actor_id=None,
            context=_suggestion_context(suggestion),
            occurred_at=self._now(),
        )
        return suggestion


__all__ = [
    "ApprovalRoutingSuggestion",
    "ApprovalSuggestionService",
    "request_approval_routing_suggestion",
]
