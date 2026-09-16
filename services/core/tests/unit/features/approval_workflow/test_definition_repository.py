"""Unit tests for ApprovalWorkflowDefinitionRepository (SKY-92, Commit 2).

Uses the repo's fake-session convention (see
``tests/unit/features/revenue_forecast/test_repository.py``): every call the
repository makes goes through a recording stub; no real database involved.

Covers the versioned lifecycle contract: drafts always get the next version,
activating a draft retires any prior active version, and retiring only
touches active definitions.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from core.features.approval_workflow.definition_repository import (
    ApprovalWorkflowDefinitionRepository,
)
from core.features.approval_workflow.models.definition import ErpApprovalWorkflowDefinitionModel

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")


class _FakeResult:
    def __init__(self, *, scalar_value: object = None, rows: list[object] | None = None) -> None:
        self._scalar = scalar_value
        self._rows = rows or []

    def scalar(self) -> object:
        return self._scalar

    def scalar_one(self) -> object:
        if self._rows:
            return self._rows[0]
        return self._scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def all(self) -> list[object]:
        return self._rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeScalars:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows

    def first(self) -> object:
        if self._rows:
            return self._rows[0]
        return None


def _definition(*, version: int, status: str = "draft", resource_type: str = "journal_entry"):
    return SimpleNamespace(
        tenant_id=TENANT,
        id=uuid.uuid4(),
        name="JE approval",
        resource_type=resource_type,
        version=version,
        definition={"steps": []},
        status=status,
        created_by=None,
        updated_by=None,
    )


class _FakeSession:
    def __init__(self, *, max_version: int | None = None) -> None:
        self._max_version = max_version
        self.added: list[object] = []
        self.flushed = 0
        self.executed: list[object] = []

    async def execute(self, stmt: object, params: object | None = None) -> _FakeResult:
        self.executed.append(stmt)
        sql = str(stmt)
        if "max(" in sql:
            return _FakeResult(scalar_value=self._max_version)
        if "advisory_xact_lock" in sql:
            return _FakeResult(scalar_value=None)
        # Queries with a single id/version filter return scalar_one_or_none.
        if "definition_id" not in sql and "version" not in sql and "status" not in sql:
            return _FakeResult(scalar_value=None)
        if "status =" in sql:
            return _FakeResult(scalar_value=None, rows=[])
        return _FakeResult(scalar_value=None)

    def add(self, model: object) -> None:
        self.added.append(model)

    async def flush(self) -> None:
        self.flushed += 1

    async def refresh(self, model: object) -> None:
        return None


class _VersionedSession(_FakeSession):
    def __init__(self, *, versions: list[object]) -> None:
        super().__init__(max_version=versions[-1].version if versions else None)
        self._versions = versions

    async def execute(self, stmt: object, params: object | None = None) -> _FakeResult:
        self.executed.append(stmt)
        sql = str(stmt)
        if "max(" in sql:
            return _FakeResult(scalar_value=self._versions[-1].version if self._versions else None)
        if "advisory_xact_lock" in sql:
            return _FakeResult(scalar_value=None)
        if "status =" in sql:
            return _FakeResult(rows=self._versions)
        if "order_by" in sql:
            return _FakeResult(rows=self._versions)
        return _FakeResult(scalar_value=None)


async def test_next_version_starts_at_one() -> None:
    session = _FakeSession(max_version=None)
    repository = ApprovalWorkflowDefinitionRepository(session)  # type: ignore[arg-type]

    version = await repository.next_version(TENANT, "journal_entry")

    assert version == 1


async def test_next_version_increments_existing() -> None:
    session = _FakeSession(max_version=7)
    repository = ApprovalWorkflowDefinitionRepository(session)  # type: ignore[arg-type]

    version = await repository.next_version(TENANT, "journal_entry")

    assert version == 8


async def test_create_draft_assigns_next_version() -> None:
    session = _FakeSession(max_version=3)
    repository = ApprovalWorkflowDefinitionRepository(session)  # type: ignore[arg-type]

    model = await repository.create_draft(
        tenant_id=TENANT,
        name="JE approval",
        resource_type="journal_entry",
        definition={"steps": []},
        created_by=None,
    )

    assert isinstance(model, ErpApprovalWorkflowDefinitionModel)
    assert model.resource_type == "journal_entry"
    assert model.version == 4
    assert model.status == "draft"
    assert session.added == [model]
    assert session.flushed == 1


async def test_get_active_returns_first_active_definition() -> None:
    active = _definition(version=2, status="active")
    session = _VersionedSession(versions=[active])
    repository = ApprovalWorkflowDefinitionRepository(session)  # type: ignore[arg-type]

    result = await repository.get_active(TENANT, "journal_entry")

    assert result is active


async def test_activate_retires_prior_active_then_seals_draft() -> None:
    prior = _definition(version=1, status="active")
    draft = _definition(version=2, status="draft")
    session = _VersionedSession(versions=[prior])
    repository = ApprovalWorkflowDefinitionRepository(session)  # type: ignore[arg-type]

    # simulate get() finding the draft
    session.get_result = draft  # type: ignore[attr-defined]

    # override: get() returns the draft
    async def fake_get(tenant_id: uuid.UUID, definition_id: uuid.UUID) -> object:
        return draft

    repository.get = fake_get  # type: ignore[method-assign]

    result = await repository.activate(TENANT, draft.id)

    assert result is draft
    assert draft.status == "active"
    assert prior.status == "retired"


async def test_activate_rejects_non_draft_definition() -> None:
    active = _definition(version=1, status="active")

    class _NonDraftSession(_FakeSession):
        async def execute(self, stmt: object) -> _FakeResult:
            self.executed.append(stmt)
            return _FakeResult(scalar_value=None)

    session = _NonDraftSession()
    repository = ApprovalWorkflowDefinitionRepository(session)  # type: ignore[arg-type]

    async def fake_get(tenant_id: uuid.UUID, definition_id: uuid.UUID) -> object:
        return active

    repository.get = fake_get  # type: ignore[method-assign]

    result = await repository.activate(TENANT, active.id)

    assert result is None
    assert active.status == "active"


async def test_retire_only_touches_active_definitions() -> None:
    draft = _definition(version=2, status="draft")
    session = _FakeSession()
    repository = ApprovalWorkflowDefinitionRepository(session)  # type: ignore[arg-type]

    async def fake_get(tenant_id: uuid.UUID, definition_id: uuid.UUID) -> object:
        return draft

    repository.get = fake_get  # type: ignore[method-assign]

    result = await repository.retire(TENANT, draft.id)

    assert result is None
    assert draft.status == "draft"
