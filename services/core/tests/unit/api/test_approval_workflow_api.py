"""Unit tests for the approval-workflow API route handlers (SKY-92, API commit).

The handlers are thin: they resolve tenant/user (deps), delegate reads to the
query service and the decision to the engine, and render envelope responses.
Testing them directly (repo convention - no app/TestClient boot) with fakes
covers the contracts the web client depends on:

- list_inbox forwards the user, tenant, now and limit and envelopes the items;
- get_instance returns the detail or raises NotFoundError (404 contract);
- decide forwards the actor + decision + reason to the engine and renders the
  outcome, including omission of an optional reason.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from core.api.v1.routers.approval_workflow import decide, get_instance, list_inbox
from core.features.approval_workflow.inbox_repository import InboxItem
from core.features.approval_workflow.query import (
    ApprovalInboxEntry,
    ApprovalSuggestionView,
)
from skyrict_common.exceptions import NotFoundError

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
INSTANCE_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
USER_APPROVER = uuid.UUID("33333333-3333-3333-3333-333333333333")
RESOURCE_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")
FIXED_NOW = datetime(2026, 9, 13, 10, 0, 0, tzinfo=UTC)


class _FakeQueryService:
    def __init__(self, *, entries: list[object] | None = None, view: object | None = None) -> None:
        self._entries = entries or []
        self._view = view
        self.calls: list[dict[str, object]] = []

    async def list_inbox(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime, limit: int = 100
    ) -> list[object]:
        self.calls.append({"tenant_id": tenant_id, "user_id": user_id, "now": now, "limit": limit})
        return self._entries

    async def get_instance(self, *, tenant_id: uuid.UUID, instance_id: uuid.UUID) -> object | None:
        self.calls.append({"tenant_id": tenant_id, "instance_id": instance_id})
        return self._view


class _FakeEngine:
    def __init__(self, result: object) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    async def decide(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self._result


def _inbox_entry(*, eligible_as: str = "assignee") -> ApprovalInboxEntry:
    instance = SimpleNamespace(
        id=INSTANCE_ID,
        resource_type="journal_entry",
        resource_id=RESOURCE_ID,
        status="pending",
        submitted_by=USER_APPROVER,
        submitted_at=FIXED_NOW,
        current_step_index=0,
    )
    step = SimpleNamespace(
        step_key="approve",
        status="pending",
        sla_due_at=FIXED_NOW,
    )
    return ApprovalInboxEntry(
        item=InboxItem(instance=instance, step=step, eligible_as=eligible_as),
        suggestion=None,
    )


def _instance_view(**overrides: object) -> SimpleNamespace:
    defaults = {
        "instance": SimpleNamespace(
            id=INSTANCE_ID,
            definition_id=uuid.UUID("99999999-9999-9999-9999-999999999999"),
            definition_version=1,
            resource_type="journal_entry",
            resource_id=RESOURCE_ID,
            status="pending",
            current_step_index=0,
            submitted_by=USER_APPROVER,
            submitted_at=FIXED_NOW,
            completed_at=None,
            sla_due_at=FIXED_NOW,
        ),
        "steps": (),
        "transitions": (),
        "suggestion": ApprovalSuggestionView(
            recommendation="approve",
            confidence="0.90",
            reasoning="Policy",
            model_used="gpt-4o",
            suggested_approver_id=USER_APPROVER,
        ),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _decision_result(**overrides: object) -> SimpleNamespace:
    defaults = {
        "instance": SimpleNamespace(
            id=INSTANCE_ID,
            resource_type="journal_entry",
            resource_id=RESOURCE_ID,
            status="approved",
        ),
        "step": SimpleNamespace(step_key="approve", status="approved"),
        "instance_completed": True,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _current_user() -> dict[str, object]:
    return {"user_id": USER_APPROVER, "tenant_id": TENANT, "token_payload": {}}


async def test_list_inbox_envelopes_entries_and_forwards_context() -> None:
    fake = _FakeQueryService(entries=[_inbox_entry()])

    result = await list_inbox(
        current_user=_current_user(),
        query_svc=fake,  # type: ignore[arg-type]
        tenant_id=TENANT,
        limit=10,
    )

    assert len(result.data) == 1
    item = result.data[0]
    assert item.instance_id == INSTANCE_ID
    assert item.resource_type == "journal_entry"
    assert item.resource_label == "Journal Entry"
    assert item.eligible_as == "assignee"
    assert item.suggestion is None
    call = fake.calls[0]
    assert call["user_id"] == USER_APPROVER
    assert call["tenant_id"] == TENANT
    assert call["limit"] == 10
    assert isinstance(call["now"], datetime)


async def test_get_instance_returns_detail_with_suggestion() -> None:
    fake = _FakeQueryService(view=_instance_view())

    result = await get_instance(
        instance_id=INSTANCE_ID,
        current_user=_current_user(),
        query_svc=fake,  # type: ignore[arg-type]
        tenant_id=TENANT,
    )

    assert result.data.instance_id == INSTANCE_ID
    assert result.data.resource_label == "Journal Entry"
    assert result.data.steps == []
    assert result.data.transitions == []
    assert result.data.suggestion is not None
    assert result.data.suggestion.recommendation == "approve"
    assert fake.calls[0]["instance_id"] == INSTANCE_ID


async def test_get_instance_missing_raises_not_found() -> None:
    fake = _FakeQueryService(view=None)

    with pytest.raises(NotFoundError):
        await get_instance(
            instance_id=INSTANCE_ID,
            current_user=_current_user(),
            query_svc=fake,  # type: ignore[arg-type]
            tenant_id=TENANT,
        )


async def test_decide_forwards_actor_decision_reason_and_renders_outcome() -> None:
    engine = _FakeEngine(result=_decision_result())

    result = await decide(
        instance_id=INSTANCE_ID,
        body=SimpleNamespace(decision="approve", reason="Looks correct"),
        current_user=_current_user(),
        engine=engine,  # type: ignore[arg-type]
        tenant_id=TENANT,
    )

    call = engine.calls[0]
    assert call["tenant_id"] == TENANT
    assert call["instance_id"] == INSTANCE_ID
    assert call["actor_id"] == USER_APPROVER
    assert call["decision"] == "approve"
    assert call["reason"] == "Looks correct"
    assert result.data.instance_status == "approved"
    assert result.data.step_key == "approve"
    assert result.data.step_status == "approved"
    assert result.data.instance_completed is True


async def test_decide_without_reason_passes_none() -> None:
    engine = _FakeEngine(result=_decision_result())

    await decide(
        instance_id=INSTANCE_ID,
        body=SimpleNamespace(decision="request_changes", reason=None),
        current_user=_current_user(),
        engine=engine,  # type: ignore[arg-type]
        tenant_id=TENANT,
    )

    assert engine.calls[0]["reason"] is None
