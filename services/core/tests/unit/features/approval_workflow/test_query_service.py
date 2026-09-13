"""Unit tests for ApprovalWorkflowQueryService (SKY-92, API commit).

The query service turns engine persistence into API read models. Using the
repo-convention fakes (SimpleNamespace rows), the tests cover:

- list_inbox decorates every pending item with its latest AI suggestion;
- list_inbox without any suggestion returns ``None`` (no fabricated AI);
- get_instance assembles the instance + steps + transitions, resolving each
  transition's step key from its step_id;
- the latest suggestion is the most recent ``ai_suggestion`` transition and
  an unparsable suggested_approver_id degrades to ``None`` (never a crash);
- a missing instance returns ``None`` before probing steps/transitions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from core.features.approval_workflow.inbox_repository import InboxItem
from core.features.approval_workflow.query import ApprovalWorkflowQueryService

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
INSTANCE_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
USER_APPROVER = uuid.UUID("33333333-3333-3333-3333-333333333333")
RESOURCE_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")
FIXED_NOW = datetime(2026, 9, 13, 10, 0, 0, tzinfo=UTC)


def _instance(**overrides: object) -> SimpleNamespace:
    defaults = {
        "id": INSTANCE_ID,
        "definition_id": uuid.UUID("99999999-9999-9999-9999-999999999999"),
        "definition_version": 1,
        "tenant_id": TENANT,
        "resource_type": "journal_entry",
        "resource_id": RESOURCE_ID,
        "status": "pending",
        "current_step_index": 0,
        "submitted_by": USER_APPROVER,
        "submitted_at": FIXED_NOW,
        "completed_at": None,
        "sla_due_at": FIXED_NOW,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _step(*, index: int = 0, status: str = "pending", **overrides: object) -> SimpleNamespace:
    defaults = {
        "id": uuid.uuid4(),
        "instance_id": INSTANCE_ID,
        "step_index": index,
        "step_key": f"approve{index}",
        "assignee_kind": "role",
        "assignee_value": "Finance Manager",
        "status": status,
        "decided_by": None,
        "decided_at": None,
        "sla_due_at": FIXED_NOW,
        "delegated_from": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _transition(
    *,
    new_state: str = "suggestion",
    actor_type: str = "ai_suggestion",
    step_id: uuid.UUID | None = None,
    context: dict[str, object] | None = None,
    **overrides: object,
) -> SimpleNamespace:
    defaults = {
        "id": uuid.uuid4(),
        "workflow_instance_id": INSTANCE_ID,
        "step_id": step_id,
        "previous_state": "pending",
        "new_state": new_state,
        "actor_id": None,
        "actor_type": actor_type,
        "reason": None,
        "context": context,
        "occurred_at": FIXED_NOW,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class _FakeInboxRepo:
    def __init__(self, items: list[InboxItem]) -> None:
        self._items = items
        self.limit: int | None = None

    async def list_pending_for_user(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime, limit: int = 100
    ) -> list[InboxItem]:
        self.limit = limit
        return self._items


class _FakeInstanceRepo:
    def __init__(
        self,
        *,
        instance: object | None,
        steps: list[object] | None = None,
        transitions: list[object] | None = None,
    ) -> None:
        self._instance = instance
        self._steps = steps or []
        self._transitions = transitions or []
        self.probed_steps: list[uuid.UUID] = []
        self.probed_transitions: list[uuid.UUID] = []

    async def get_instance(self, tenant_id: uuid.UUID, instance_id: uuid.UUID) -> object | None:
        return self._instance

    async def list_steps(self, tenant_id: uuid.UUID, instance_id: uuid.UUID) -> list[object]:
        self.probed_steps.append(instance_id)
        return self._steps

    async def list_transitions(self, tenant_id: uuid.UUID, instance_id: uuid.UUID) -> list[object]:
        self.probed_transitions.append(instance_id)
        return self._transitions


def _service(
    *,
    items: list[InboxItem] | None = None,
    instance: object | None = None,
    steps: list[object] | None = None,
    transitions: list[object] | None = None,
) -> tuple[ApprovalWorkflowQueryService, _FakeInboxRepo, _FakeInstanceRepo]:
    inbox = _FakeInboxRepo(items or [])
    instances = _FakeInstanceRepo(instance=instance, steps=steps, transitions=transitions)
    return (
        ApprovalWorkflowQueryService(inbox=inbox, instances=instances),
        inbox,
        instances,
    )


def _entry(*, delegated_from: uuid.UUID | None = None) -> InboxItem:
    step = _step()
    return InboxItem(
        instance=_instance(),
        step=step,
        eligible_as="delegate" if delegated_from else "assignee",
        delegated_from=delegated_from,
    )


async def test_list_inbox_decorates_items_with_latest_suggestion() -> None:
    suggestion_context = {
        "recommendation": "approve",
        "confidence": "0.92",
        "reasoning": "Matches policy",
        "model_used": "gpt-4o",
        "suggested_approver_id": str(USER_APPROVER),
    }
    service, inbox, _instances = _service(
        items=[_entry()],
        transitions=[_transition(context=suggestion_context)],
    )

    entries = await service.list_inbox(
        tenant_id=TENANT, user_id=USER_APPROVER, now=FIXED_NOW, limit=25
    )

    assert len(entries) == 1
    assert entries[0].item.eligible_as == "assignee"
    assert entries[0].suggestion is not None
    assert entries[0].suggestion.recommendation == "approve"
    assert entries[0].suggestion.confidence == "0.92"
    assert entries[0].suggestion.reasoning == "Matches policy"
    assert entries[0].suggestion.model_used == "gpt-4o"
    assert entries[0].suggestion.suggested_approver_id == USER_APPROVER
    assert inbox.limit == 25


async def test_list_inbox_no_suggestion_is_none() -> None:
    service, _, instances = _service(items=[_entry()], transitions=[])

    entries = await service.list_inbox(tenant_id=TENANT, user_id=USER_APPROVER, now=FIXED_NOW)

    assert len(entries) == 1
    assert entries[0].suggestion is None
    assert instances.probed_transitions == [INSTANCE_ID]


async def test_latest_suggestion_prefers_most_recent() -> None:
    service, _, _ = _service(
        items=[_entry()],
        transitions=[
            _transition(context={"recommendation": "older", "suggested_approver_id": None}),
            _transition(
                context={
                    "recommendation": "newer",
                    "confidence": "0.50",
                    "reasoning": "",
                    "model_used": "gpt-4o-mini",
                    "suggested_approver_id": "not-a-uuid",
                }
            ),
        ],
    )

    entries = await service.list_inbox(tenant_id=TENANT, user_id=USER_APPROVER, now=FIXED_NOW)

    suggestion = entries[0].suggestion
    assert suggestion is not None
    assert suggestion.recommendation == "newer"
    assert suggestion.confidence == "0.50"
    # Unparsable approver id degrades to None (fail-safe, never a crash).
    assert suggestion.suggested_approver_id is None


async def test_get_instance_assembles_steps_and_resolves_transition_step_keys() -> None:
    step = _step(index=0, key="approve0")
    service, _, instances = _service(
        instance=_instance(),
        steps=[step],
        transitions=[
            _transition(new_state="submitted", actor_type="system", step_id=None),
            _transition(
                new_state="suggestion",
                actor_type="ai_suggestion",
                step_id=step.id,
                context={"recommendation": "approve"},
            ),
        ],
    )

    view = await service.get_instance(tenant_id=TENANT, instance_id=INSTANCE_ID)

    assert view is not None
    assert view.instance.resource_type == "journal_entry"
    assert len(view.steps) == 1
    assert view.steps[0].step_key == "approve0"
    assert len(view.transitions) == 2
    assert view.transitions[0].step_key is None
    assert view.transitions[1].step_key == "approve0"
    assert view.suggestion is not None
    assert view.suggestion.recommendation == "approve"
    assert instances.probed_steps == [INSTANCE_ID]
    # get_instance probes transitions twice: once for the audit trail and once
    # for the latest suggestion (both read from the same append-only store).
    assert instances.probed_transitions == [INSTANCE_ID, INSTANCE_ID]


async def test_get_instance_missing_short_circuits() -> None:
    service, _, instances = _service(instance=None)

    view = await service.get_instance(tenant_id=TENANT, instance_id=INSTANCE_ID)

    assert view is None
    assert instances.probed_steps == []
    assert instances.probed_transitions == []
