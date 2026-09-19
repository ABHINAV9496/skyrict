"""Unit tests for ApprovalEngine submit/decide + audit (SKY-92, engine commit).

Uses a recording fake repository (repo convention) so the engine's state
machine and audit behavior are tested without a database:

- submit resolves steps in order, computes SLA due times from the injectable
  clock, records the submission transition and returns the pending instance;
- auto-approval routing evaluates each step's ``auto_approval.when`` against
  the routing amount in definition order: matching steps are approved by the
  system actor; the first non-matching step becomes the pending human queue;
  when every step auto-approves the instance completes ``auto_approved`` and
  the module resource port's ``on_approved`` (system actor) is called;
- decide enforces instance/step pending state, resolves role / permission /
  user-list membership AT DECISION TIME (a revoked user fails closed) and
  appends an audit transition per decision; a completed instance notifies the
  module resource port (approved / rejected / request_changes);
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
    AmountAtLeastCondition,
    AmountBelowCondition,
    AutoApprovalRule,
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
        decided_by=USER_APPROVER,
    )


def _instance(*, status: str = "pending", current_step_index: int = 0):
    return SimpleNamespace(
        id=INSTANCE_ID,
        tenant_id=TENANT,
        status=status,
        current_step_index=current_step_index,
        resource_type="journal_entry",
        resource_id=uuid.UUID("77777777-7777-7777-7777-777777777777"),
    )


class FakeResourcePort:
    """Records module-side callbacks the engine drives through the port."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def submit_for_approval(self, **kwargs: object) -> None:
        self.calls.append(("submit_for_approval", kwargs))

    async def on_approved(self, **kwargs: object) -> None:
        self.calls.append(("on_approved", kwargs))

    async def on_rejected(self, **kwargs: object) -> None:
        self.calls.append(("on_rejected", kwargs))

    async def on_request_changes(self, **kwargs: object) -> None:
        self.calls.append(("on_request_changes", kwargs))

    async def on_cancelled(self, **kwargs: object) -> None:
        self.calls.append(("on_cancelled", kwargs))


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
        self.decided_step.decided_by = kwargs.get("decided_by")
        self.decided_step.delegated_from = kwargs.get("delegated_from")
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


class FakeApprovalDelegationRepository:
    """Returns preset active grants; scope filtering is the engine's job."""

    def __init__(self, grants: list[object] | None = None) -> None:
        self.grants = grants or []
        self.calls: list[tuple[str, dict]] = []

    async def list_grants_from_delegators(self, **kwargs: object) -> list[object]:
        self.calls.append(("list_grants_from_delegators", kwargs))
        return list(self.grants)


def _grant(
    *,
    delegator: uuid.UUID,
    delegate: uuid.UUID,
    permission: str | None = None,
    resource_type: str | None = None,
):
    return SimpleNamespace(
        delegator=delegator,
        delegate=delegate,
        permission=permission,
        resource_type=resource_type,
    )


def _engine(
    repo: FakeApprovalWorkflowInstanceRepository,
    *,
    port: FakeResourcePort | None = None,
    delegation_repo: FakeApprovalDelegationRepository | None = None,
):
    return ApprovalEngine(  # type: ignore[arg-type]
        repo,
        now=lambda: FIXED_NOW,
        resource_port=port,
        delegation_repository=delegation_repo,
    )


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


async def test_decide_accepts_api_verb_decision_approve() -> None:
    """The API contract sends ``approve``/``reject`` - normalize to the engine statuses."""
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    engine = _engine(repo)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_APPROVER,
        decision="approve",
        reason="looks good",
    )

    assert result.instance.status == "approved"
    assert result.instance_completed is True
    assert repo.decided_step.status == "approved"
    assert repo.transitions[-1]["new_state"] == "approved"


async def test_decide_accepts_api_verb_decision_reject() -> None:
    """The API contract sends ``reject`` - normalize to the engine's ``rejected``."""
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    engine = _engine(repo)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_APPROVER,
        decision="reject",
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


# ----------------------------------------------------- auto-approval routing


def _auto_step(key: str, condition: object) -> WorkflowStep:
    step = _step(UserListAssignee(user_ids=[USER_APPROVER]), key=key)
    step.auto_approval = AutoApprovalRule(when=condition)  # type: ignore[attr-defined]
    return step


async def test_submit_auto_approves_step_below_threshold_and_completes_instance() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    port = FakeResourcePort()
    engine = _engine(repo, port=port)
    definition = _definition(
        [_auto_step("auto", AmountBelowCondition(amount=Decimal("10000.0000")))]
    )

    result = await engine.submit(
        tenant_id=TENANT,
        definition=definition,
        definition_id=uuid.uuid4(),
        resource_type="journal_entry",
        resource_id=uuid.uuid4(),
        amount=Decimal("5000.0000"),
        submitted_by=USER_APPROVER,
    )

    assert result.auto_approved is True
    assert result.instance.status == "auto_approved"
    assert repo.decided_step.status == "approved"
    assert repo.decided_step.decided_by is None
    auto_transition = repo.transitions[-1]
    assert auto_transition["new_state"] == "auto_approved"
    assert auto_transition["actor_type"] == ACTOR_SYSTEM
    assert auto_transition["actor_id"] is None
    assert auto_transition["context"] == {"condition": "amount_below"}
    # module port notified that the resource is approved by the system actor
    port_calls = [call[0] for call in port.calls]
    assert "on_approved" in port_calls
    approved_call = next(call for call in port.calls if call[0] == "on_approved")
    assert approved_call[1]["decider_actor_type"] == ACTOR_SYSTEM


async def test_submit_at_threshold_routes_to_human_queue() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    port = FakeResourcePort()
    engine = _engine(repo, port=port)
    definition = _definition(
        [_auto_step("auto", AmountBelowCondition(amount=Decimal("10000.0000")))]
    )

    result = await engine.submit(
        tenant_id=TENANT,
        definition=definition,
        definition_id=uuid.uuid4(),
        resource_type="journal_entry",
        resource_id=uuid.uuid4(),
        amount=Decimal("10000.0000"),
        submitted_by=USER_APPROVER,
    )

    assert result.auto_approved is False
    assert result.instance.status == "pending"
    assert port.calls == []
    # nothing auto-decided; step stays pending for the human queue
    assert repo.decided_step is None
    assert repo.instance_updates[-1]["current_step_index"] == 0


async def test_submit_missing_amount_never_auto_approves() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    engine = _engine(repo)
    definition = _definition(
        [_auto_step("auto", AmountBelowCondition(amount=Decimal("10000.0000")))]
    )

    result = await engine.submit(
        tenant_id=TENANT,
        definition=definition,
        definition_id=uuid.uuid4(),
        resource_type="journal_entry",
        resource_id=uuid.uuid4(),
        amount=None,
        submitted_by=USER_APPROVER,
    )

    assert result.auto_approved is False
    assert result.instance.status == "pending"
    assert repo.decided_step is None


async def test_submit_without_auto_approval_stays_pending() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    engine = _engine(repo)
    definition = _definition([_step(UserListAssignee(user_ids=[USER_APPROVER]))])

    result = await engine.submit(
        tenant_id=TENANT,
        definition=definition,
        definition_id=uuid.uuid4(),
        resource_type="journal_entry",
        resource_id=uuid.uuid4(),
        amount=Decimal("5000.0000"),
        submitted_by=USER_APPROVER,
    )

    assert result.auto_approved is False
    assert result.instance.status == "pending"
    assert repo.decided_step is None


async def test_submit_mixed_chain_auto_approves_prefix_and_waits_on_next() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    engine = _engine(repo)
    definition = _definition(
        [
            _auto_step("auto", AmountBelowCondition(amount=Decimal("10000.0000"))),
            _step(RoleAssignee(role="finance_manager"), key="cf0"),
        ]
    )

    result = await engine.submit(
        tenant_id=TENANT,
        definition=definition,
        definition_id=uuid.uuid4(),
        resource_type="journal_entry",
        resource_id=uuid.uuid4(),
        amount=Decimal("5000.0000"),
        submitted_by=USER_APPROVER,
    )

    # first step auto-approved, second step is now the pending queue
    assert result.auto_approved is False
    assert result.instance.status == "pending"
    assert result.instance.current_step_index == 1
    assert repo.decided_step.status == "approved"
    assert repo.decided_step.decided_by is None


async def test_submit_auto_approves_all_steps_in_chain() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    port = FakeResourcePort()
    engine = _engine(repo, port=port)
    definition = _definition(
        [
            _auto_step("one", AmountBelowCondition(amount=Decimal("10000.0000"))),
            _auto_step("two", AmountAtLeastCondition(amount=Decimal("1.0000"))),
        ]
    )

    result = await engine.submit(
        tenant_id=TENANT,
        definition=definition,
        definition_id=uuid.uuid4(),
        resource_type="journal_entry",
        resource_id=uuid.uuid4(),
        amount=Decimal("5000.0000"),
        submitted_by=USER_APPROVER,
    )

    assert result.auto_approved is True
    assert result.instance.status == "auto_approved"
    assert result.instance.current_step_index == 1
    assert any(call[0] == "on_approved" for call in port.calls)


# ------------------------------------------------------ module resource port


async def test_decide_completed_approval_notifies_module_port() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    port = FakeResourcePort()
    engine = _engine(repo, port=port)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_APPROVER,
        decision="approved",
        reason="verified",
    )

    assert result.instance_completed is True
    approved_call = next(call for call in port.calls if call[0] == "on_approved")
    assert approved_call[1]["decider_actor_type"] == ACTOR_HUMAN
    assert approved_call[1]["reason"] == "verified"
    assert approved_call[1]["resource_type"] == "journal_entry"


async def test_decide_completed_rejection_notifies_module_port() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    port = FakeResourcePort()
    engine = _engine(repo, port=port)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_APPROVER,
        decision="rejected",
        reason="amount exceeded",
    )

    assert result.instance.status == "rejected"
    rejected_call = next(call for call in port.calls if call[0] == "on_rejected")
    assert rejected_call[1]["reason"] == "amount exceeded"


async def test_decide_request_changes_on_final_step_completes_and_notifies() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    port = FakeResourcePort()
    engine = _engine(repo, port=port)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_APPROVER,
        decision="request_changes",
        reason="fix the line items",
    )

    assert result.instance_completed is True
    assert result.instance.status == "request_changes"
    # regression: the OLD engine KeyError'd on a final-step request_changes
    changes_call = next(call for call in port.calls if call[0] == "on_request_changes")
    assert changes_call[1]["reason"] == "fix the line items"
    assert changes_call[1]["resource_id"] == _instance().resource_id


async def test_decide_without_port_keeps_module_unaware() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    engine = _engine(repo)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_APPROVER,
        decision="approved",
    )

    assert result.instance_completed is True
    assert result.instance.status == "approved"


# ---------------------------------------------------------------- delegation


async def test_decide_delegate_of_assignee_may_decide() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    delegation_repo = FakeApprovalDelegationRepository(
        grants=[_grant(delegator=USER_APPROVER, delegate=USER_STRANGER)]
    )
    engine = _engine(repo, delegation_repo=delegation_repo)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_STRANGER,
        decision="approved",
    )

    assert result.instance.status == "approved"
    # the delegate is not the direct assignee...
    transition = repo.transitions[-1]
    assert transition["actor_type"] == "delegated"
    assert transition["actor_id"] == USER_STRANGER
    assert transition["delegated_actor"] == USER_APPROVER
    assert transition["original_assignee"] == USER_APPROVER
    # ... and the step's effective-assignee triple records the delegator
    assert repo.decided_step.delegated_from == USER_APPROVER


async def test_decide_delegation_with_matching_resource_scope_decides() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    delegation_repo = FakeApprovalDelegationRepository(
        grants=[
            _grant(
                delegator=USER_APPROVER,
                delegate=USER_STRANGER,
                resource_type="journal_entry",
            )
        ]
    )
    engine = _engine(repo, delegation_repo=delegation_repo)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_STRANGER,
        decision="approved",
    )

    assert result.instance.status == "approved"
    assert repo.transitions[-1]["actor_type"] == "delegated"


async def test_decide_delegation_with_mismatched_resource_scope_fails_closed() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    delegation_repo = FakeApprovalDelegationRepository(
        grants=[
            _grant(
                delegator=USER_APPROVER,
                delegate=USER_STRANGER,
                resource_type="payroll_run",
            )
        ]
    )
    engine = _engine(repo, delegation_repo=delegation_repo)

    with pytest.raises(PermissionDeniedError):
        await engine.decide(
            tenant_id=TENANT,
            instance_id=INSTANCE_ID,
            actor_id=USER_STRANGER,
            decision="approved",
        )

    assert repo.transitions == []
    assert repo.decided_step is None


async def test_decide_delegation_with_matching_permission_scope_decides() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    repo.instance = _instance()
    repo.steps = [
        _step_row(
            index=0,
            key="approve",
            kind="permission",
            value="erp.finance.approve",
        )
    ]
    delegation_repo = FakeApprovalDelegationRepository(
        grants=[
            _grant(
                delegator=USER_APPROVER,
                delegate=USER_STRANGER,
                permission="erp.finance.approve",
            )
        ]
    )
    engine = _engine(repo, delegation_repo=delegation_repo)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_STRANGER,
        decision="approved",
    )

    assert result.instance.status == "approved"
    assert repo.transitions[-1]["actor_type"] == "delegated"


async def test_decide_delegation_with_wildcard_permission_scope_decides() -> None:
    # A grant scoped to the owner wildcard covers any permission-keyed step.
    repo = FakeApprovalWorkflowInstanceRepository()
    repo.instance = _instance()
    repo.steps = [
        _step_row(
            index=0,
            key="approve",
            kind="permission",
            value="erp.finance.approve",
        )
    ]
    delegation_repo = FakeApprovalDelegationRepository(
        grants=[
            _grant(
                delegator=USER_APPROVER,
                delegate=USER_STRANGER,
                permission="*",
            )
        ]
    )
    engine = _engine(repo, delegation_repo=delegation_repo)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_STRANGER,
        decision="approved",
    )

    assert result.instance.status == "approved"
    assert repo.transitions[-1]["actor_type"] == "delegated"


async def test_decide_permission_scoped_grant_ignored_for_user_step() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)  # users-keyed step
    delegation_repo = FakeApprovalDelegationRepository(
        grants=[
            _grant(
                delegator=USER_APPROVER,
                delegate=USER_STRANGER,
                permission="erp.finance.approve",
            )
        ]
    )
    engine = _engine(repo, delegation_repo=delegation_repo)

    with pytest.raises(PermissionDeniedError):
        await engine.decide(
            tenant_id=TENANT,
            instance_id=INSTANCE_ID,
            actor_id=USER_STRANGER,
            decision="approved",
        )

    assert repo.transitions == []


async def test_decide_delegate_without_matching_grant_fails_closed() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    # grant exists but points at a different delegate
    delegation_repo = FakeApprovalDelegationRepository(
        grants=[_grant(delegator=USER_APPROVER, delegate=USER_SECOND)]
    )
    engine = _engine(repo, delegation_repo=delegation_repo)

    with pytest.raises(PermissionDeniedError):
        await engine.decide(
            tenant_id=TENANT,
            instance_id=INSTANCE_ID,
            actor_id=USER_STRANGER,
            decision="approved",
        )

    assert repo.transitions == []


async def test_decide_without_delegation_repository_denies_delegate() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    engine = _engine(repo)  # no delegation repository wired

    with pytest.raises(PermissionDeniedError):
        await engine.decide(
            tenant_id=TENANT,
            instance_id=INSTANCE_ID,
            actor_id=USER_STRANGER,
            decision="approved",
        )

    assert repo.transitions == []


async def test_decide_direct_assignee_stays_human_even_when_delegate() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    # USER_APPROVER is both the direct assignee and a delegate of USER_SECOND
    delegation_repo = FakeApprovalDelegationRepository(
        grants=[_grant(delegator=USER_SECOND, delegate=USER_APPROVER)]
    )
    engine = _engine(repo, delegation_repo=delegation_repo)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_APPROVER,
        decision="approved",
    )

    assert result.instance.status == "approved"
    transition = repo.transitions[-1]
    assert transition["actor_type"] == ACTOR_HUMAN
    assert transition["delegated_actor"] is None
    assert transition["original_assignee"] == USER_APPROVER
    assert repo.decided_step.delegated_from is None


async def test_decide_delegated_completion_notifies_port_with_delegated_actor() -> None:
    repo = FakeApprovalWorkflowInstanceRepository()
    _single_step_engine(repo)
    port = FakeResourcePort()
    delegation_repo = FakeApprovalDelegationRepository(
        grants=[_grant(delegator=USER_APPROVER, delegate=USER_STRANGER)]
    )
    engine = _engine(repo, port=port, delegation_repo=delegation_repo)

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=USER_STRANGER,
        decision="approved",
    )

    assert result.instance_completed is True
    approved_call = next(call for call in port.calls if call[0] == "on_approved")
    assert approved_call[1]["decider_actor_type"] == "delegated"
