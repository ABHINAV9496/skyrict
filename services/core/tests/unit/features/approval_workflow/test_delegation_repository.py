"""Unit tests for ApprovalDelegationRepository (SKY-92, delegation/inbox commit).

Uses a recording fake session (repo convention) so grants, revocation and the
engine-side / inbox-side probes are tested without a database:

- create persists an active grant with ``effective_from`` defaulting to the
  caller's ``now`` when no explicit window start is given;
- revoke soft-revokes (row preserved for audit) and returns None when the
  grant is already gone or already revoked;
- list_active_for_delegate returns the active, non-revoked grants matching the
  window at ``now``;
- resolve_active_delegators dedupes the delegators behind those grants;
- list_grants_from_delegators (engine probe) short-circuits on an empty
  delegator set without issuing a query, and otherwise returns the active
  grants FROM any of the set.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from core.features.approval_workflow.delegation_repository import ApprovalDelegationRepository
from core.features.approval_workflow.models.delegation import ErpApprovalDelegationModel

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
FIXED_NOW = datetime(2026, 9, 13, 10, 0, 0, tzinfo=UTC)

DELEGATOR = uuid.UUID("33333333-3333-3333-3333-333333333333")
DELEGATE = uuid.UUID("44444444-4444-4444-4444-444444444444")
CREATED_BY = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _grant(
    *, delegator: uuid.UUID = DELEGATOR, delegate: uuid.UUID = DELEGATE
) -> ErpApprovalDelegationModel:
    return ErpApprovalDelegationModel(
        tenant_id=TENANT,
        delegator=delegator,
        delegate=delegate,
        effective_from=FIXED_NOW,
        created_by=CREATED_BY,
    )


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
    """Records every call the repository makes; none hits a real database."""

    def __init__(self, *, rows: list[object] | None = None, scalar: object = None) -> None:
        self._rows = rows or []
        self._scalar = scalar
        self.queries: list[str] = []
        self.added: list[object] = []
        self.flushes = 0
        self.refreshes = 0

    async def execute(self, stmt: object) -> _FakeResult:
        self.queries.append(str(stmt))
        return _FakeResult(scalar_value=self._scalar, rows=self._rows)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def refresh(self, obj: object) -> None:
        self.refreshes += 1


async def test_create_persists_grant_with_now_default_window_start() -> None:
    session = _FakeSession(scalar=_grant())
    repository = ApprovalDelegationRepository(session)  # type: ignore[arg-type]

    model = await repository.create(
        tenant_id=TENANT,
        delegator=DELEGATOR,
        delegate=DELEGATE,
        created_by=CREATED_BY,
        now=FIXED_NOW,
    )

    assert session.added == [model]
    assert session.flushes == 1
    assert session.refreshes == 1
    assert model.tenant_id == TENANT
    assert model.delegator == DELEGATOR
    assert model.delegate == DELEGATE
    assert model.created_by == CREATED_BY
    assert model.effective_from == FIXED_NOW
    assert model.effective_to is None
    assert model.permission is None
    assert model.resource_type is None


async def test_create_persists_scoped_grant_with_explicit_window() -> None:
    session = _FakeSession(scalar=_grant())
    repository = ApprovalDelegationRepository(session)  # type: ignore[arg-type]
    starts = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    ends = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)

    model = await repository.create(
        tenant_id=TENANT,
        delegator=DELEGATOR,
        delegate=DELEGATE,
        created_by=CREATED_BY,
        now=FIXED_NOW,
        permission="erp.finance.approve",
        resource_type="journal_entry",
        effective_from=starts,
        effective_to=ends,
    )

    assert model.permission == "erp.finance.approve"
    assert model.resource_type == "journal_entry"
    assert model.effective_from == starts
    assert model.effective_to == ends


async def test_revoke_soft_revokes_active_grant() -> None:
    grant = _grant()
    session = _FakeSession(scalar=grant)
    repository = ApprovalDelegationRepository(session)  # type: ignore[arg-type]

    model = await repository.revoke(
        tenant_id=TENANT,
        delegation_id=grant.id,
        revoked_at=FIXED_NOW,
    )

    assert model is grant
    assert model.revoked_at == FIXED_NOW
    assert session.flushes == 1


async def test_revoke_missing_grant_returns_none() -> None:
    session = _FakeSession(scalar=None)
    repository = ApprovalDelegationRepository(session)  # type: ignore[arg-type]

    model = await repository.revoke(
        tenant_id=TENANT,
        delegation_id=uuid.uuid4(),
        revoked_at=FIXED_NOW,
    )

    assert model is None
    assert session.flushes == 0


async def test_list_active_for_delegate_returns_rows_from_probe() -> None:
    rows = [_grant(), _grant(delegate=uuid.UUID("66666666-6666-6666-6666-666666666666"))]
    session = _FakeSession(rows=rows)
    repository = ApprovalDelegationRepository(session)  # type: ignore[arg-type]

    result = await repository.list_active_for_delegate(TENANT, DELEGATE, FIXED_NOW)

    assert result == rows
    assert len(session.queries) == 1
    assert "erp_approval_delegations" in session.queries[0]


async def test_resolve_active_delegators_dedupes_delegators() -> None:
    other = uuid.UUID("77777777-7777-7777-7777-777777777777")
    rows = [
        _grant(delegator=DELEGATOR),
        _grant(delegator=DELEGATOR),
        _grant(delegator=other),
    ]
    session = _FakeSession(rows=rows)
    repository = ApprovalDelegationRepository(session)  # type: ignore[arg-type]

    result = await repository.resolve_active_delegators(
        tenant_id=TENANT,
        delegate=DELEGATE,
        now=FIXED_NOW,
    )

    assert set(result) == {DELEGATOR, other}


async def test_list_grants_from_delegators_short_circuits_empty_set() -> None:
    session = _FakeSession(rows=[])
    repository = ApprovalDelegationRepository(session)  # type: ignore[arg-type]

    result = await repository.list_grants_from_delegators(
        tenant_id=TENANT,
        delegators=[],
        now=FIXED_NOW,
    )

    assert result == []
    assert session.queries == []


async def test_list_grants_from_delegators_returns_active_grants() -> None:
    rows = [_grant(), _grant(delegator=uuid.UUID("88888888-8888-8888-8888-888888888888"))]
    session = _FakeSession(rows=rows)
    repository = ApprovalDelegationRepository(session)  # type: ignore[arg-type]

    result = await repository.list_grants_from_delegators(
        tenant_id=TENANT,
        delegators=[DELEGATOR],
        now=FIXED_NOW,
    )

    assert result == rows
    assert len(session.queries) == 1
