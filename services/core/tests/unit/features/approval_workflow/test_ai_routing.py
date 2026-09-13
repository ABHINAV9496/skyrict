"""Unit tests for AI routing suggestions (SKY-92, AI-routing commit).

Covers the transport client with ``httpx.MockTransport`` (no network) and the
service with the repo fake-session convention:

- upstream path, Authorization + tenant-slug header hygiene and payload shape;
- full suggestion mapping, abstention, recommendation validation and
  confidence bounds (fail closed);
- upstream errors, invalid JSON and non-object bodies raise
  :class:`AiServiceUnavailableError`;
- the service records a non-authority audit transition (actor type
  ``ai_suggestion``, never a state change) and degrades to ``None`` when the
  AI service is absent or failing - an AI failure never blocks approval.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

import core.features.approval_workflow.ai_routing as ai_routing_module
from core.core.exceptions import AiServiceUnavailableError
from core.features.approval_workflow.ai_routing import (
    ApprovalRoutingSuggestion,
    ApprovalSuggestionService,
    request_approval_routing_suggestion,
)
from core.features.approval_workflow.instance_repository import (
    ApprovalWorkflowInstanceRepository,
)

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
INSTANCE_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
STEP_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
RESOURCE_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
FIXED_NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ai.test")


# --------------------------------------------------------------- transport


async def test_success_parses_suggestion() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/ai/approval/routing-suggest"
        assert request.headers["authorization"] == "Bearer tok"
        assert request.headers["x-tenant-slug"] == "acme-inc"
        payload = json.loads(request.content)
        assert payload["resource_type"] == "journal_entry"
        assert payload["resource_id"] == str(RESOURCE_ID)
        assert payload["amount"] == "12500.00"
        assert payload["description"] == "Credit memo for vendor ACME"
        return httpx.Response(
            200,
            json={
                "recommendation": "approve",
                "confidence": 0.87,
                "reasoning": "Matches the purchasing policy for this limit.",
                "model_used": "gpt-4.1",
            },
        )

    async with _client(handler) as client:
        result = await request_approval_routing_suggestion(
            client,
            authorization="Bearer tok",
            tenant_slug="acme-inc",
            resource_type="journal_entry",
            resource_id=RESOURCE_ID,
            amount=Decimal("12500.00"),
            description="Credit memo for vendor ACME",
        )
    assert result == ApprovalRoutingSuggestion(
        recommendation="approve",
        confidence=Decimal("0.87"),
        reasoning="Matches the purchasing policy for this limit.",
        model_used="gpt-4.1",
    )


async def test_success_parses_suggested_approver() -> None:
    approver_id = uuid.UUID("aaaa0000-0000-4000-8000-000000000001")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "recommendation": "approve",
                "confidence": 0.9,
                "reasoning": "Fits the finance approval desk.",
                "model_used": "gpt-4.1",
                "suggested_approver_id": str(approver_id),
            },
        )

    async with _client(handler) as client:
        result = await request_approval_routing_suggestion(
            client,
            authorization=None,
            tenant_slug=None,
            resource_type="journal_entry",
            resource_id=RESOURCE_ID,
            amount=Decimal("12500.00"),
            description="Credit memo",
        )
    assert result is not None
    assert result.suggested_approver_id == approver_id


async def test_invalid_suggested_approver_id_is_field_abstention() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "recommendation": "approve",
                "reasoning": "Still useful.",
                "suggested_approver_id": "not-a-uuid",
            },
        )

    async with _client(handler) as client:
        result = await request_approval_routing_suggestion(
            client,
            authorization=None,
            tenant_slug=None,
            resource_type="journal_entry",
            resource_id=RESOURCE_ID,
            amount=Decimal("12500.00"),
            description="Credit memo",
        )
    assert result is not None
    assert result.recommendation == "approve"
    assert result.suggested_approver_id is None


async def test_abstains_when_payload_empty() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    async with _client(handler) as client:
        result = await request_approval_routing_suggestion(
            client,
            authorization=None,
            tenant_slug=None,
            resource_type="payroll_run",
            resource_id=RESOURCE_ID,
            amount=None,
            description="",
        )
    assert result is None


async def test_unknown_recommendation_abstains_but_keeps_reasoning() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"recommendation": "maybe", "confidence": 0.95, "reasoning": "Unclear."}
        )

    async with _client(handler) as client:
        result = await request_approval_routing_suggestion(
            client,
            authorization=None,
            tenant_slug=None,
            resource_type="journal_entry",
            resource_id=RESOURCE_ID,
            amount=Decimal("500"),
            description="x",
        )
    assert result is not None
    assert result.recommendation is None
    assert result.confidence is None
    assert result.reasoning == "Unclear."


async def test_confidence_out_of_range_is_none() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"recommendation": "approve", "confidence": 1.5})

    async with _client(handler) as client:
        result = await request_approval_routing_suggestion(
            client,
            authorization=None,
            tenant_slug=None,
            resource_type="journal_entry",
            resource_id=RESOURCE_ID,
            amount=Decimal("500"),
            description="x",
        )
    assert result is not None
    assert result.recommendation == "approve"
    assert result.confidence is None


async def test_upstream_error_raises() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"title": "upstream failed"})

    async with _client(handler) as client:
        with pytest.raises(AiServiceUnavailableError):
            await request_approval_routing_suggestion(
                client,
                authorization=None,
                tenant_slug=None,
                resource_type="journal_entry",
                resource_id=RESOURCE_ID,
                amount=Decimal("500"),
                description="x",
            )


async def test_invalid_json_raises() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>")

    async with _client(handler) as client:
        with pytest.raises(AiServiceUnavailableError):
            await request_approval_routing_suggestion(
                client,
                authorization=None,
                tenant_slug=None,
                resource_type="journal_entry",
                resource_id=RESOURCE_ID,
                amount=Decimal("500"),
                description="x",
            )


async def test_non_object_body_raises() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    async with _client(handler) as client:
        with pytest.raises(AiServiceUnavailableError):
            await request_approval_routing_suggestion(
                client,
                authorization=None,
                tenant_slug=None,
                resource_type="journal_entry",
                resource_id=RESOURCE_ID,
                amount=Decimal("500"),
                description="x",
            )


# ----------------------------------------------------------------- service


class _FakeResult:
    def __init__(self, *, scalar_value: object = None, rows: list[object] | None = None) -> None:
        self._scalar = scalar_value
        self._rows = rows or []

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[object]:
        return self._rows


class _FakeSession:
    """Records added transition rows (repo conventions)."""

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.flushes = 0
        self.refreshes = 0
        self.added: list[object] = []

    async def execute(self, stmt: object) -> _FakeResult:
        self.queries.append(str(stmt))
        return _FakeResult()

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def refresh(self, obj: object) -> None:
        self.refreshes += 1


def _instance() -> SimpleNamespace:
    return SimpleNamespace(
        id=INSTANCE_ID,
        resource_type="journal_entry",
        resource_id=RESOURCE_ID,
    )


def _step() -> SimpleNamespace:
    return SimpleNamespace(id=STEP_ID, status="pending")


async def test_service_short_circuits_without_client() -> None:
    session = _FakeSession()
    service = ApprovalSuggestionService(
        repository=ApprovalWorkflowInstanceRepository(session),  # type: ignore[arg-type]
        now=lambda: FIXED_NOW,
    )

    result = await service.suggest_and_record(
        client=None,
        authorization=None,
        tenant_slug=None,
        tenant_id=TENANT,
        instance=_instance(),  # type: ignore[arg-type]
        step=_step(),  # type: ignore[arg-type]
        amount=Decimal("12500.00"),
        description="Credit memo",
    )

    assert result is None
    assert session.added == []
    assert session.flushes == 0


async def test_service_records_suggestion_audit_transition() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "recommendation": "reject",
                "confidence": 0.62,
                "reasoning": "Duplicate vendor invoice detected.",
                "model_used": "gpt-4.1",
            },
        )

    session = _FakeSession()
    service = ApprovalSuggestionService(
        repository=ApprovalWorkflowInstanceRepository(session),  # type: ignore[arg-type]
        now=lambda: FIXED_NOW,
    )

    async with _client(handler) as client:
        result = await service.suggest_and_record(
            client=client,
            authorization="Bearer tok",
            tenant_slug="acme-inc",
            tenant_id=TENANT,
            instance=_instance(),  # type: ignore[arg-type]
            step=_step(),  # type: ignore[arg-type]
            amount=Decimal("12500.00"),
            description="Credit memo",
        )

    assert result is not None
    assert result.recommendation == "reject"
    assert len(session.added) == 1
    transition = session.added[0]
    assert transition.tenant_id == TENANT
    assert transition.workflow_instance_id == INSTANCE_ID
    assert transition.step_id == STEP_ID
    assert transition.previous_state == "pending"
    assert transition.new_state == "suggestion"
    assert transition.actor_type == "ai_suggestion"
    assert transition.actor_id is None
    assert transition.context["recommendation"] == "reject"
    assert transition.context["confidence"] == "0.62"
    assert transition.context["reasoning"] == "Duplicate vendor invoice detected."
    assert transition.context["model_used"] == "gpt-4.1"
    assert transition.occurred_at == FIXED_NOW


async def test_service_keeps_eligible_suggested_approver() -> None:
    approver_id = uuid.UUID("aaaa0000-0000-4000-8000-000000000001")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "recommendation": "approve",
                "confidence": 0.9,
                "suggested_approver_id": str(approver_id),
            },
        )

    session = _FakeSession()
    service = ApprovalSuggestionService(
        repository=ApprovalWorkflowInstanceRepository(session),  # type: ignore[arg-type]
        now=lambda: FIXED_NOW,
    )
    async with _client(handler) as client:
        result = await service.suggest_and_record(
            client=client,
            authorization=None,
            tenant_slug=None,
            tenant_id=TENANT,
            instance=_instance(),  # type: ignore[arg-type]
            step=_step(),  # type: ignore[arg-type]
            amount=Decimal("12500.00"),
            description="Credit memo",
            allowed_approver_ids={approver_id},
        )

    assert result is not None
    assert result.suggested_approver_id == approver_id
    assert len(session.added) == 1
    assert session.added[0].context["suggested_approver_id"] == str(approver_id)


async def test_service_strips_ineligible_suggested_approver() -> None:
    """Core validates the AI's person against the step's eligible set."""
    approver_id = uuid.UUID("aaaa0000-0000-4000-8000-000000000001")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "recommendation": "approve",
                "confidence": 0.9,
                "reasoning": "Fits the finance approval desk.",
                "suggested_approver_id": str(approver_id),
            },
        )

    session = _FakeSession()
    service = ApprovalSuggestionService(
        repository=ApprovalWorkflowInstanceRepository(session),  # type: ignore[arg-type]
        now=lambda: FIXED_NOW,
    )
    async with _client(handler) as client:
        result = await service.suggest_and_record(
            client=client,
            authorization=None,
            tenant_slug=None,
            tenant_id=TENANT,
            instance=_instance(),  # type: ignore[arg-type]
            step=_step(),  # type: ignore[arg-type]
            amount=Decimal("12500.00"),
            description="Credit memo",
            allowed_approver_ids={uuid.UUID("bbbb0000-0000-4000-8000-000000000002")},
        )

    # The person is stripped (never surfaced, never recorded) while the rest
    # of the recommendation survives and is audited as-is.
    assert result is not None
    assert result.recommendation == "approve"
    assert result.suggested_approver_id is None
    assert len(session.added) == 1
    assert session.added[0].context["suggested_approver_id"] is None


async def test_service_degrades_on_transport_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(*args, **kwargs) -> ApprovalRoutingSuggestion:
        raise AiServiceUnavailableError("AI agent service did not respond")

    monkeypatch.setattr(ai_routing_module, "request_approval_routing_suggestion", broken)
    session = _FakeSession()
    service = ApprovalSuggestionService(
        repository=ApprovalWorkflowInstanceRepository(session),  # type: ignore[arg-type]
        now=lambda: FIXED_NOW,
    )

    async with httpx.AsyncClient(base_url="http://ai.test") as client:
        result = await service.suggest_and_record(
            client=client,
            authorization=None,
            tenant_slug=None,
            tenant_id=TENANT,
            instance=_instance(),  # type: ignore[arg-type]
            step=_step(),  # type: ignore[arg-type]
            amount=Decimal("12500.00"),
            description="Credit memo",
        )

    assert result is None
    assert session.added == []
