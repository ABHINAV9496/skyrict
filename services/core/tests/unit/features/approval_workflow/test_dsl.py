"""Unit tests for the approval workflow DSL (SKY-92).

The DSL is the versioned JSON document contract that modules use to describe
approval chains. These tests lock down:

- parsing for each assignee kind (role / permission / user-list)
- the exact demo threshold semantics (8k auto-approves, 12k routes to the
  finance-approver queue) with exact ``Decimal`` comparison
- JSON round-tripping that keeps money exact (never float)
- structural validation (duplicate keys, SLA ordering, empty collections)
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.features.approval_workflow.dsl import (
    AmountAtLeastCondition,
    AmountBelowCondition,
    AutoApprovalRule,
    PermissionAssignee,
    RoleAssignee,
    RoutingStrategy,
    SlaPolicy,
    UserListAssignee,
    WorkflowDefinition,
    WorkflowStep,
)

DEMO_RESOURCE_TYPE = "journal_entry"
USER_1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_2 = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _permission_step(
    *,
    key: str = "approval",
    permission: str = "erp.finance.approve",
    auto_approve_below: str | None = None,
) -> WorkflowStep:
    step = WorkflowStep(
        key=key,
        assignee=PermissionAssignee(permission=permission),
        sla=SlaPolicy(hours=24, reminder_before_hours=1),
    )
    if auto_approve_below is not None:
        step.auto_approval = AutoApprovalRule(
            when=AmountBelowCondition(amount=Decimal(auto_approve_below))
        )
    return step


def _demo_definition(*, auto_approve_below: str = "10000.0000") -> WorkflowDefinition:
    """The SKY-92 acceptance workflow: <10k auto-approves, >=10k needs a finance approver."""
    return WorkflowDefinition(
        name="Journal entry posting approval",
        resource_type=DEMO_RESOURCE_TYPE,
        version=1,
        steps=[
            _permission_step(auto_approve_below=auto_approve_below),
        ],
    )


# ---------------------------------------------------------------------------
# Parsing each assignee kind
# ---------------------------------------------------------------------------


def test_role_assignee_workflow_parses() -> None:
    definition = WorkflowDefinition(
        name="PO suggestion approval",
        resource_type="po_suggestion",
        version=1,
        steps=[WorkflowStep(key="review", assignee=RoleAssignee(role="finance_manager"))],
    )
    assert definition.steps[0].assignee.kind == "role"
    assert definition.steps[0].assignee.role == "finance_manager"  # type: ignore[union-attr]


def test_user_list_assignee_workflow_parses() -> None:
    definition = WorkflowDefinition(
        name="Expense line approval",
        resource_type="expense_line",
        version=3,
        steps=[WorkflowStep(key="review", assignee=UserListAssignee(user_ids=[USER_1, USER_2]))],
    )
    assert definition.steps[0].assignee.kind == "users"
    assert definition.steps[0].assignee.user_ids == [USER_1, USER_2]  # type: ignore[union-attr]


def test_permission_assignee_workflow_parses() -> None:
    definition = _demo_definition()
    assert definition.resource_type == DEMO_RESOURCE_TYPE
    assert definition.version == 1
    assert definition.steps[0].assignee.kind == "permission"
    assert definition.steps[0].assignee.permission == "erp.finance.approve"  # type: ignore[union-attr]
    assert definition.steps[0].routing == RoutingStrategy.DETERMINISTIC
    assert definition.steps[0].delegation_allowed is True


# ---------------------------------------------------------------------------
# Demo threshold semantics (exact Decimal comparison)
# ---------------------------------------------------------------------------


def test_demo_definition_carries_auto_approval_threshold() -> None:
    definition = _demo_definition()
    rule = definition.steps[0].auto_approval
    assert rule is not None
    assert isinstance(rule.when, AmountBelowCondition)
    assert rule.when.amount == Decimal("10000.0000")


def test_auto_approval_condition_discriminators() -> None:
    below = AmountBelowCondition(amount=Decimal("10000.0000"))
    at_least = AmountAtLeastCondition(amount=Decimal("10000.0000"))
    assert below.kind == "amount_below"
    assert at_least.kind == "amount_at_least"
    # Demo semantics: 8,000 is strictly below, 12,000 is at-or-above the bound.
    assert Decimal("8000.0000") < below.amount
    assert not (Decimal("12000.0000") < below.amount)
    assert Decimal("12000.0000") >= at_least.amount


def test_amount_round_trips_exactly_through_json() -> None:
    """Money must survive JSON serialization as an exact string, never a float."""
    parts = _demo_definition().model_dump(mode="json")
    assert parts["steps"][0]["auto_approval"]["when"]["amount"] == "10000.0000"
    assert isinstance(parts["steps"][0]["auto_approval"]["when"]["amount"], str)
    rebuilt = WorkflowDefinition.model_validate(parts)
    assert rebuilt.steps[0].auto_approval is not None
    assert rebuilt.steps[0].auto_approval.when.amount == Decimal("10000.0000")
    # Float arithmetic introduces binary noise that must never enter the DSL
    # (Decimal("0.1") + Decimal("0.2") is exact; float 0.1 + 0.2 is not).
    assert Decimal("0.3000") == Decimal("0.1000") + Decimal("0.2000")
    assert Decimal(str(0.1 + 0.2)) != Decimal("0.3000")


# ---------------------------------------------------------------------------
# Structural validation
# ---------------------------------------------------------------------------


def test_rejects_empty_step_chain() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        WorkflowDefinition(
            name="Empty",
            resource_type=DEMO_RESOURCE_TYPE,
            version=1,
            steps=[],
        )


def test_rejects_duplicate_step_keys() -> None:
    with pytest.raises(ValidationError, match="duplicate step key"):
        WorkflowDefinition(
            name="Dup keys",
            resource_type=DEMO_RESOURCE_TYPE,
            version=1,
            steps=[
                WorkflowStep(key="approval", assignee=RoleAssignee(role="finance_manager")),
                WorkflowStep(key="approval", assignee=RoleAssignee(role="admin")),
            ],
        )


def test_rejects_reminder_at_sla_boundary() -> None:
    with pytest.raises(ValidationError, match="reminder_before_hours"):
        WorkflowStep(
            key="approval",
            assignee=RoleAssignee(role="finance_manager"),
            sla=SlaPolicy(hours=1, reminder_before_hours=1),
        )


def test_rejects_reminder_after_sla() -> None:
    with pytest.raises(ValidationError, match="reminder_before_hours"):
        WorkflowStep(
            key="approval",
            assignee=RoleAssignee(role="finance_manager"),
            sla=SlaPolicy(hours=2, reminder_before_hours=3),
        )


def test_rejects_zero_sla_hours() -> None:
    with pytest.raises(ValidationError, match="greater than 0"):
        SlaPolicy(hours=0)


def test_rejects_zero_or_negative_amount_threshold() -> None:
    with pytest.raises(ValidationError):
        AmountBelowCondition(amount=Decimal("0.0000"))
    with pytest.raises(ValidationError):
        AmountAtLeastCondition(amount=Decimal("-1.0000"))


def test_rejects_empty_user_list() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        UserListAssignee(user_ids=[])


def test_rejects_unknown_assignee_kind() -> None:
    with pytest.raises(ValidationError, match="kind"):
        WorkflowDefinition(
            name="Bad assignee",
            resource_type=DEMO_RESOURCE_TYPE,
            version=1,
            steps=[
                WorkflowStep(
                    key="approval",
                    assignee={"kind": "department", "name": "finance"},  # type: ignore[arg-type]
                )
            ],
        )


def test_rejects_blank_definition_fields() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition(
            name="",
            resource_type=DEMO_RESOURCE_TYPE,
            version=1,
            steps=[WorkflowStep(key="approval", assignee=RoleAssignee(role="finance_manager"))],
        )
    with pytest.raises(ValidationError):
        WorkflowDefinition(
            name="x",
            resource_type="",
            version=1,
            steps=[WorkflowStep(key="approval", assignee=RoleAssignee(role="finance_manager"))],
        )
