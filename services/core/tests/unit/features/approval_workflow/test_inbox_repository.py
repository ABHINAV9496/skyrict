"""Unit tests for ApprovalWorkflowInboxRepository (SKY-92, delegation/inbox commit).

Uses a queue-based fake session (repo convention) so inbox eligibility - direct
assignee membership vs active delegation - is tested without a database:

- empty tenant inbox short-circuits to [] without probing roles;
- a direct assignee appears with ``eligible_as='assignee'`` (user list, role
  membership, permission grant);
- a delegate of an assignee appears with ``eligible_as='delegate'`` and the
  delegator recorded;
- grants whose resource_type or permission scope does not match the step and
  instance are excluded (fail closed);
- a delegator who does not actually hold the step's role/permission cannot
  make the step appear in the delegate's inbox.

The fake session returns rows per statement (instances / steps / role names /
permission arrays), mirroring the repository's query order.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from core.features.approval_workflow.inbox_repository import (
    ApprovalWorkflowInboxRepository,
    InboxItem,
)

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
INSTANCE_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
FIXED_NOW = datetime(2026, 9, 13, 10, 0, 0, tzinfo=UTC)

USER_APPROVER = uuid.UUID("33333333-3333-3333-3333-333333333333")
USER_DELEGATE = uuid.UUID("44444444-4444-4444-4444-444444444444")
USER_STRANGER = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _instance(**overrides: object) -> SimpleNamespace:
    defaults = {
        "id": INSTANCE_ID,
        "tenant_id": TENANT,
        "status": "pending",
        "current_step_index": 0,
        "resource_type": "journal_entry",
        "resource_id": uuid.UUID("77777777-7777-7777-7777-777777777777"),
        "sla_due_at": FIXED_NOW,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _step(*, kind: str, value: str, index: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        instance_id=INSTANCE_ID,
        step_index=index,
        step_key=f"approve{index}",
        assignee_kind=kind,
        assignee_value=value,
        status="pending",
    )


def _grant(
    *,
    delegator: uuid.UUID,
    delegate: uuid.UUID,
    permission: str | None = None,
    resource_type: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        delegator=delegator,
        delegate=delegate,
        permission=permission,
        resource_type=resource_type,
    )


class _FakeDelegationRepo:
    """Stand-in for ApprovalDelegationRepository.list_active_for_delegate.

    Mirrors the real repository's ``delegate == :delegate`` filter so grants
    for other users never leak into a probe.
    """

    def __init__(self, grants: list[object] | None = None) -> None:
        self.grants = grants or []
        self.calls: list[tuple[object, object]] = []

    async def list_active_for_delegate(
        self, tenant_id: object, delegate: object, now: object
    ) -> list[object]:
        self.calls.append((tenant_id, delegate))
        return [g for g in self.grants if g.delegate == delegate]


class _FakeResult:
    def __init__(self, *, rows: list[object] | None = None, scalar: object = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[object]:
        return self._rows


class _FakeSession:
    """Returns one preset row batch per execute, in query order."""

    def __init__(self, batches: list[list[object]]) -> None:
        self._batches = list(batches)
        self.queries: list[str] = []

    async def execute(self, stmt: object) -> _FakeResult:
        self.queries.append(str(stmt))
        rows = self._batches.pop(0) if self._batches else []
        return _FakeResult(rows=rows)


def _inbox(
    sessions: _FakeSession,
    *,
    delegation_repo: _FakeDelegationRepo | None = None,
) -> ApprovalWorkflowInboxRepository:
    return ApprovalWorkflowInboxRepository(
        sessions,  # type: ignore[arg-type]
        delegation_repository=delegation_repo,  # type: ignore[arg-type]
    )


async def test_empty_tenant_returns_empty_inbox_without_role_probes() -> None:
    session = _FakeSession(batches=[[], []])
    inbox = _inbox(session)

    items = await inbox.list_pending_for_user(
        tenant_id=TENANT,
        user_id=USER_APPROVER,
        now=FIXED_NOW,
    )

    assert items == []
    # only the pending-instances probe ran; steps/roles never needed
    assert len(session.queries) == 1


async def test_direct_assignee_via_user_list_appears_as_assignee() -> None:
    session = _FakeSession(
        batches=[
            [_instance()],
            [_step(kind="users", value=str(USER_APPROVER))],
            [],
            [],
        ]
    )
    inbox = _inbox(session)

    items = await inbox.list_pending_for_user(
        tenant_id=TENANT,
        user_id=USER_APPROVER,
        now=FIXED_NOW,
    )

    assert len(items) == 1
    assert items[0].eligible_as == "assignee"
    assert items[0].delegated_from is None
    assert items[0].instance.resource_type == "journal_entry"


async def test_direct_assignee_via_role_membership_appears_as_assignee() -> None:
    session = _FakeSession(
        batches=[
            [_instance()],
            [_step(kind="role", value="finance_manager")],
            ["finance_manager"],
            [],
        ]
    )
    inbox = _inbox(session)

    items = await inbox.list_pending_for_user(
        tenant_id=TENANT,
        user_id=USER_APPROVER,
        now=FIXED_NOW,
    )

    assert len(items) == 1
    assert items[0].eligible_as == "assignee"


async def test_direct_assignee_via_permission_grant_appears_as_assignee() -> None:
    session = _FakeSession(
        batches=[
            [_instance()],
            [_step(kind="permission", value="erp.finance.approve")],
            [],
            [["erp.finance.approve"]],
        ]
    )
    inbox = _inbox(session)

    items = await inbox.list_pending_for_user(
        tenant_id=TENANT,
        user_id=USER_APPROVER,
        now=FIXED_NOW,
    )

    assert len(items) == 1
    assert items[0].eligible_as == "assignee"


async def test_delegate_of_assignee_appears_as_delegate_with_delegator() -> None:
    session = _FakeSession(
        batches=[
            [_instance()],
            [_step(kind="users", value=str(USER_APPROVER))],
            [],
            [],
            [],
            [],
        ]
    )
    delegation_repo = _FakeDelegationRepo(
        grants=[_grant(delegator=USER_APPROVER, delegate=USER_DELEGATE)]
    )
    inbox = _inbox(session, delegation_repo=delegation_repo)

    items = await inbox.list_pending_for_user(
        tenant_id=TENANT,
        user_id=USER_DELEGATE,
        now=FIXED_NOW,
    )

    assert len(items) == 1
    assert items[0].eligible_as == "delegate"
    assert items[0].delegated_from == USER_APPROVER
    # the delegate probe was asked about USER_DELEGATE
    assert delegation_repo.calls == [(TENANT, USER_DELEGATE)]


async def test_delegate_also_probes_delegators_roles_and_permissions() -> None:
    # USER_APPROVER also probes as a delegator (roles + permissions batches).
    session = _FakeSession(
        batches=[
            [_instance()],
            [_step(kind="role", value="finance_manager")],
            [],
            [],
            ["finance_manager"],
            [],
        ]
    )
    delegation_repo = _FakeDelegationRepo(
        grants=[_grant(delegator=USER_APPROVER, delegate=USER_DELEGATE)]
    )
    inbox = _inbox(session, delegation_repo=delegation_repo)

    items = await inbox.list_pending_for_user(
        tenant_id=TENANT,
        user_id=USER_DELEGATE,
        now=FIXED_NOW,
    )

    # the delegator holds the role, so the delegate sees the item
    assert len(items) == 1
    assert items[0].eligible_as == "delegate"
    assert items[0].delegated_from == USER_APPROVER


async def test_delegator_without_role_cannot_put_step_in_delegate_inbox() -> None:
    session = _FakeSession(
        batches=[
            [_instance()],
            [_step(kind="role", value="finance_manager")],
            [],
            [],
            [],  # delegator holds NO roles
            [],
        ]
    )
    delegation_repo = _FakeDelegationRepo(
        grants=[_grant(delegator=USER_APPROVER, delegate=USER_DELEGATE)]
    )
    inbox = _inbox(session, delegation_repo=delegation_repo)

    items = await inbox.list_pending_for_user(
        tenant_id=TENANT,
        user_id=USER_DELEGATE,
        now=FIXED_NOW,
    )

    assert items == []


async def test_resource_scoped_grant_mismatch_excluded() -> None:
    session = _FakeSession(
        batches=[
            [_instance(resource_type="journal_entry")],
            [_step(kind="users", value=str(USER_APPROVER))],
            [],
            [],
            [],
            [],
        ]
    )
    delegation_repo = _FakeDelegationRepo(
        grants=[
            _grant(
                delegator=USER_APPROVER,
                delegate=USER_DELEGATE,
                resource_type="payroll_run",
            )
        ]
    )
    inbox = _inbox(session, delegation_repo=delegation_repo)

    items = await inbox.list_pending_for_user(
        tenant_id=TENANT,
        user_id=USER_DELEGATE,
        now=FIXED_NOW,
    )

    assert items == []


async def test_permission_scoped_grant_ignored_for_user_list_step() -> None:
    session = _FakeSession(
        batches=[
            [_instance()],
            [_step(kind="users", value=str(USER_APPROVER))],
            [],
            [],
            [],
            [],
        ]
    )
    delegation_repo = _FakeDelegationRepo(
        grants=[
            _grant(
                delegator=USER_APPROVER,
                delegate=USER_DELEGATE,
                permission="erp.finance.approve",
            )
        ]
    )
    inbox = _inbox(session, delegation_repo=delegation_repo)

    items = await inbox.list_pending_for_user(
        tenant_id=TENANT,
        user_id=USER_DELEGATE,
        now=FIXED_NOW,
    )

    assert items == []


async def test_permission_scoped_grant_matches_permission_keyed_step() -> None:
    session = _FakeSession(
        batches=[
            [_instance()],
            [_step(kind="permission", value="erp.finance.approve")],
            [],
            [],
            [],
            [["erp.finance.approve"]],
        ]
    )
    delegation_repo = _FakeDelegationRepo(
        grants=[
            _grant(
                delegator=USER_APPROVER,
                delegate=USER_DELEGATE,
                permission="erp.finance.approve",
            )
        ]
    )
    inbox = _inbox(session, delegation_repo=delegation_repo)

    items = await inbox.list_pending_for_user(
        tenant_id=TENANT,
        user_id=USER_DELEGATE,
        now=FIXED_NOW,
    )

    assert len(items) == 1
    assert items[0].eligible_as == "delegate"


async def test_stranger_without_membership_or_grant_sees_nothing() -> None:
    session = _FakeSession(
        batches=[
            [_instance()],
            [_step(kind="users", value=str(USER_APPROVER))],
            [],
            [],
            [],
            [],
        ]
    )
    delegation_repo = _FakeDelegationRepo(
        grants=[_grant(delegator=USER_APPROVER, delegate=USER_DELEGATE)]
    )
    inbox = _inbox(session, delegation_repo=delegation_repo)

    items = await inbox.list_pending_for_user(
        tenant_id=TENANT,
        user_id=USER_STRANGER,
        now=FIXED_NOW,
    )

    assert items == []


async def test_mixed_inbox_direct_and_delegated_items() -> None:
    session = _FakeSession(
        batches=[
            [_instance()],
            [
                _step(kind="users", value=str(USER_DELEGATE), index=0),
                _step(kind="users", value=str(USER_APPROVER), index=1),
            ],
            [],
            [],
            [],
            [],
        ]
    )
    delegation_repo = _FakeDelegationRepo(
        grants=[_grant(delegator=USER_APPROVER, delegate=USER_DELEGATE)]
    )
    inbox = _inbox(session, delegation_repo=delegation_repo)

    items = await inbox.list_pending_for_user(
        tenant_id=TENANT,
        user_id=USER_DELEGATE,
        now=FIXED_NOW,
    )

    assert len(items) == 2
    by_kind = {item.eligible_as: item for item in items}
    assert by_kind["assignee"].delegated_from is None
    assert by_kind["delegate"].delegated_from == USER_APPROVER
    assert isinstance(items[0], InboxItem)
