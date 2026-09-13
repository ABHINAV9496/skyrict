"""Unit tests for ApprovalEngine submit/decide + audit (SKY-92, engine commit).

Uses a recording fake repository (repo convention) so the engine's state
machine and audit behavior are tested without a database:

- submit resolves steps in order, computes SLA due times from the injectable
  clock, records the submission transition and returns the pending instance;
- decide enforces instance/step pending state, resolves role / permission /
  user-list membership AT DECISION TIME (a revoked user fails closed) and
  appends an audit transition per decision;
- the instance advances to the next pending step and completes only after the
  final step.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.features.approval_workflow.dsl import (
    PermissionAssignee,
    RoleAssignee,
    UserListAssignee,
    WorkflowDefinition,
    WorkflowStep,
)
from core.features.approval_workflow.engine import (
    ACTOR_HUMAN,
    ACTOR_SYSTEM,
    ApprovalEngine,
)
from skyrict_common.exceptions import ConflictError, NotFoundError, PermissionDeniedError

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
INSTANCE_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
FIXED_NOW = datetime(2026, 9, 13, 10, 0, 0, tzinfo=UTC)

USER_APPROVER = uuid.UUID("33333333-3333-3333-3333-333333333333")
USER_SECOND = uuid.UUID("44444444-4444-4444-4444-444444444444")
USER_OTHER = uuid.UUID("55555555-5555-5555-5555-555555555555")
USER_STRANGER = uuid.UUID("66666666-6666-6666-6666-666666666666")


def _step(assignee: object, key: str = "approve") -> WorkflowStep:
    return WorkflowStep(key=key, assignee=assignee)


def _definition(steps: list[WorkflowStep]) -> WorkflowDefinition:
    return WorkflowDefinition(
        name="JE approval",
        resource_type="journal_entry",
        version=1,
        steps=steps,
    )


def _step_row(*, index: int, key: str, kind: str, value: str, status: str = "pending"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        instance_id=INSTANCE_ID,
        step_index=index,
        step_key=key,
        assignee_kind=kind,
        assignee_value=value,
        status=status,
    )


def _instance(*, status: str = "pending", current_step_index: int = 0):
    return SimpleNamespace(
        id=INSTANCE_ID,
        tenant_id=TENANT,
        status=status,
        current_step_index=current_step_index,
    )


class FakeApprovalWorkflowInstanceRepository:
    """Records every call; returns what the engine needs for orchestration."""

    def __init__(
        self,
        *,
        role_members: dict[str, list[uuid.UUID]] | None = None,
        permission_members: dict[str, list[uuid.UUID]] | None = None,
        instance: object = None,
        steps: list[object] | None = None,
    ) -> None:
        self.role_members = role_members or {}
        self.permission_members = permission_members or {}
        self.instance = instance
        self.steps = steps or []
        self.calls: list[tuple[str, dict]] = []
        self.created_instance: object | None = None
        self.created_steps: list[dict] = []
        self.decided_step: object | None = None
        self.transitions: list[dict] = []
        self.instance_updates: list[dict] = []

    async def create_instance(self, **kwargs: object) -> object:
        self.calls.append(("create_instance", kwargs))
        self.created_steps = list(kwargs["steps"])  # type: ignore[arg-type]
        self.created_instance = _instance()
        # The engine reads steps back after creation; mirror the persisted rows.
        self.steps = [
            SimpleNamespace(
                id=uuid.uuid4(),
                instance_id=INSTANCE_ID,
                step_index=index,
                step_key=row["step_key"],
                assignee_kind=row["assignee_kind"],
                assignee_value=row["assignee_value"],
                status="pending",
            )
            for index, row in enumerate(self.created_steps)
        ]
        return self.created_instance

    async def get_instance(self, tenant_id: uuid.UUID, instance_id: uuid.UUID) -> object | None:
        self.calls.append(("get_instance", {"tenant_id": tenant_id, "instance_id": instance_id}))
        return self.instance

    async def list_steps(self, tenant_id: uuid.UUID, instance_id: uuid.UUID) -> list[object]:
        self.calls.append(("list_steps", {"tenant_id": tenant_id, "instance_id": instance_id}))
        return list(self.steps)

    async def update_step_decision(self, **kwargs: object) -> object:
        self.calls.append(("update_step_decision", kwargs))
        self.decided_step = _step_row(
            index=kwargs["step_id"] and 0,  # type: ignore[arg-type]
            key="approve",
            kind="users",
            value=str(USER_APPROVER),
            status=kwargs["status"],  # type: ignore[arg-type]
        )
        return self.decided_step

    async def update_instance_status(self, **kwargs: object) -> object:
        self.calls.append(("update_instance_status", kwargs))
        self.instance_updates.append(kwargs)
        self.instance = _instance(
            status=kwargs["status"],  # type: ignore[arg-type]
            current_step_index=kwargs["current_step_index"],  # type: ignore[arg-type]
        )
        return self.instance

    async def record_transition(self, **kwargs: object) -> object:
        self.calls.append(("record_transition", kwargs))
        self.transitions.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    async def resolve_role_members(self, tenant_id: uuid.UUID, role: str) -> list[uuid.UUID]:
        self.calls.append(("resolve_role_members", {"tenant_id": tenant_id, "role": role}))
        return self.role_members.get(role, [])

    async def resolve_permission_members(
        self, tenant_id: uuid.UUID, permission: str
    ) -> list[uuid.UUID]:
        self.calls.append(
            ("resolve_permission_members", {"tenant_id": tenant_id, "permission": permission})
        )
        return self.permission_members.get(permission, [])

    async def list_transitions(self, tenant_id: uuid.UUID, instance_id: uuid.UUID) -> list[object]:
        return []


def _engine(repo: FakeApprovalWorkflowInstanceRepository) -> ApprovalEngine:
    return ApprovalEngine(repo, now=lambda: FIXED_NOW)  # type: ignore[arg-type]


# ------------------------------------------------------------------ submit


async def test_submit_creates_pending_instance_with_resolved_steps_and_audit() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    with_role = _step(RoleAssignee(role="finance_manager"), key="first")
    with_permission = _step(PermissionAssignee(permission="erp.finance.approve"), key="second")
    engine = _engine(repo)
    definition = _definition([with_role, with_permission])

    result = await engine.submit(
        tenant_id=TENANT,
        definition=definition,
        definition_id=uuid.uuid4(),
        resource_type="journal_entry",
        resource_id=uuid.uuid4(),
        amount=Decimal("12000.0000"),
        submitted_by=USER_APPROVER,
    )

    assert result.instance.status == "pending"
    assert result.steps
    assert repo.created_steps[0]["step_key"] == "first"
    assert repo.created_steps[0]["assignee_kind"] == "role"
    assert repo.created_steps[0]["assignee_value"] == "finance_manager"
    assert repo.created_steps[1]["assignee_kind"] == "permission"
    assert repo.created_steps[1]["assignee_value"] == "erp.finance.approve"
    assert repo.transitions[-1]["new_state"] == "submitted"
    assert repo.transitions[-1]["actor_type"] == ACTOR_SYSTEM
    assert repo.transitions[-1]["context"] == {"amount": "12000.0000"}


async def test_submit_serializes_user_list_assignee() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    engine = _engine(repo)
    definition = _definition([_step(UserListAssignee(user_ids=[USER_APPROVER, USER_SECOND]))])

    await engine.submit(
        tenant_id=TENANT,
        definition=definition,
        definition_id=uuid.uuid4(),
        resource_type="journal_entry",
        resource_id=uuid.uuid4(),
        amount=Decimal("100.0000"),
        submitted_by=USER_APPROVER,
    )

    stored = repo.created_steps[0]
    assert stored["assignee_kind"] == "users"
    assert stored["assignee_value"] == f"{USER_APPROVER},{USER_SECOND}"


async def test_submit_computes_sla_due_from_injectable_clock() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    engine = _engine(repo)
    engine._now = lambda: FIXED_NOW  # type: ignore[attr-defined]
    step = _step(UserListAssignee(user_ids=[USER_APPROVER]))
    step.sla = SimpleNamespace(hours=24)  # type: ignore[attr-defined]
    definition = _definition([step])

    await engine.submit(
        tenant_id=TENANT,
        definition=definition,
        definition_id=uuid.uuid4(),
        resource_type="journal_entry",
        resource_id=uuid.uuid4(),
        amount=None,
        submitted_by=USER_APPROVER,
    )

    assert repo.created_steps[0]["sla_due_at"] == FIXED_NOW + timedelta(hours=24)


async def test_submit_without_sla_leaves_due_at_none() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    engine = _engine(repo)
    definition = _definition([_step(UserListAssignee(user_ids=[USER_APPROVER]))])

    await engine.submit(
        tenant_id=TENANT,
        definition=definition,
        definition_id=uuid.uuid4(),
        resource_type="journal_entry",
        resource_id=uuid.uuid4(),
        amount=None,
        submitted_by=USER_APPROVER,
    )

    assert repo.created_steps[0]["sla_due_at"] is None


# ------------------------------------------------------------------ decide


def _single_step_engine(repo: FakeApprovalWorkflowInstanceRepository):
    repo.instance = _instance()
    repo.steps = [_step_row(index=0, key="approve", kind="users", value=str(USER_APPROVER))]
    return repo


async def test_decide_approves_current_step_and_completes_instance() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    engine = _engine(repo)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_APPROVER,
        decision="approved",
        reason="looks good",
    )

    assert result.instance.status == "approved"
    assert result.instance_completed is True
    assert repo.decided_step.status == "approved"
    transition = repo.transitions[-1]
    assert transition["previous_state"] == "pending"
    assert transition["new_state"] == "approved"
    assert transition["actor_type"] == ACTOR_HUMAN
    assert transition["actor_id"] == USER_APPROVER
    assert transition["reason"] == "looks good"


async def test_decide_rejects_and_completes_as_rejected() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    engine = _engine(repo)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_APPROVER,
        decision="rejected",
        reason="amount exceeded",
    )

    assert result.instance.status == "rejected"
    assert result.instance_completed is True
    assert repo.transitions[-1]["new_state"] == "rejected"


async def test_decide_role_membership_checked_at_decision_time() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    repo.instance = _instance()
    # Stored assignee is a role; membership is resolved NOW (not at submit).
    repo.steps = [_step_row(index=0, key="approve", kind="role", value="finance_manager")]
    repo.role_members = {"finance_manager": [USER_APPROVER, USER_SECOND]}
    engine = _engine(repo)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_APPROVER,
        decision="approved",
    )

    assert result.instance.status == "approved"
    assert ("resolve_role_members", {"tenant_id": TENANT, "role": "finance_manager"}) in [
        (call[0], call[1]) for call in repo.calls
    ]


async def test_decide_permission_membership_fails_closed_for_stranger() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    repo.instance = _instance()
    repo.steps = [_step_row(index=0, key="approve", kind="permission", value="erp.finance.approve")]
    repo.permission_members = {"erp.finance.approve": [USER_APPROVER]}
    engine = _engine(repo)

    with pytest.raises(PermissionDeniedError):
        await engine.decide(
            tenant_id=TENANT,
            instance_id=INSTANCE_ID,
            actor_id=USER_STRANGER,
            decision="approved",
        )

    assert repo.transitions == []
    assert repo.decided_step is None


async def test_decide_user_list_membership_from_stored_value() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    repo.instance = _instance()
    repo.steps = [
        _step_row(
            index=0,
            key="approve",
            kind="users",
            value=f"{USER_APPROVER},{USER_SECOND}",
        )
    ]
    engine = _engine(repo)

    # Both listed users may decide.
    for actor in (USER_APPROVER, USER_SECOND):
        repo.instance = _instance()
        result = await engine.decide(
            tenant_id=TENANT,
            instance_id=INSTANCE_ID,
            actor_id=actor,
            decision="approved",
        )
        assert result.instance.status == "approved"


async def test_decide_missing_instance_raises_not_found() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    repo.instance = None
    engine = _engine(repo)

    with pytest.raises(NotFoundError):
        await engine.decide(
            tenant_id=TENANT,
            instance_id=INSTANCE_ID,
            actor_id=USER_APPROVER,
            decision="approved",
        )


async def test_decide_non_pending_instance_raises_conflict() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    repo.instance = _instance(status="approved")
    repo.steps = [_step_row(index=0, key="approve", kind="users", value=str(USER_APPROVER))]
    engine = _engine(repo)

    with pytest.raises(ConflictError):
        await engine.decide(
            tenant_id=TENANT,
            instance_id=INSTANCE_ID,
            actor_id=USER_APPROVER,
            decision="approved",
        )


async def test_decide_already_decided_step_raises_conflict() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    repo.instance = _instance()
    repo.steps = [
        _step_row(index=0, key="approve", kind="users", value=str(USER_APPROVER), status="approved")
    ]
    engine = _engine(repo)

    with pytest.raises(ConflictError):
        await engine.decide(
            tenant_id=TENANT,
            instance_id=INSTANCE_ID,
            actor_id=USER_APPROVER,
            decision="approved",
        )


async def test_decide_advances_to_next_pending_step() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    repo.instance = _instance()
    repo.steps = [
        _step_row(index=0, key="first", kind="users", value=str(USER_APPROVER)),
        _step_row(index=1, key="second", kind="users", value=str(USER_SECOND)),
    ]
    engine = _engine(repo)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_APPROVER,
        decision="approved",
    )

    assert result.instance_completed is False
    assert result.instance.status == "pending"
    updates = repo.instance_updates
    assert updates[-1]["current_step_index"] == 1


async def test_decide_last_step_completes_chain() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    repo.instance = _instance()
    repo.steps = [
        _step_row(index=0, key="first", kind="users", value=str(USER_APPROVER), status="approved"),
        _step_row(index=1, key="second", kind="users", value=str(USER_SECOND)),
    ]
    repo.instance.current_step_index = 1
    engine = _engine(repo)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_SECOND,
        decision="approved",
    )

    assert result.instance_completed is True
    assert result.instance.status == "approved"
    assert repo.decided_step.status == "approved"


async def test_decide_unsupported_decision_raises_conflict() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    engine = _engine(repo)

    with pytest.raises(ConflictError):
        await engine.decide(
            tenant_id=TENANT,
            instance_id=INSTANCE_ID,
            actor_id=USER_APPROVER,
            decision="maybe",
        )
