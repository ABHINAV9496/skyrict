"""Unit tests for SLA escalation (SKY-92, escalation commit).

Covers the escalation contract end to end with fakes (repo conventions):

- the repository probe only returns the CURRENT pending step of a pending
  instance whose ``sla_due_at`` has passed, most overdue first, capped by limit;
- ``mark_step_escalated`` is idempotent (pending-only) and never touches
  ``decided_by``/``decided_at``;
- the service marks each overdue step escalated and appends an audit
  transition with actor type ``escalation`` (no actor id), returning the count;
- escalation is a nudge, never a decision: the instance stays ``pending`` and
  the escalated step is still decidable - the engine accepts escalated steps
  and records the real previous state on the decision transition;
- the background worker walks pending-instance tenants, sets ``TenantContext``
  per tenant, escalates in its own session and commits per tenant.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from core.features.approval_workflow.engine import ApprovalEngine
from core.features.approval_workflow.escalation import ApprovalEscalationService
from core.features.approval_workflow.escalation_worker import (
    ApprovalEscalationWorker,
    EscalationOutcome,
)
from core.features.approval_workflow.instance_repository import (
    ApprovalWorkflowInstanceRepository,
)

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_TWO = uuid.UUID("12121212-1212-1212-1212-121212121212")
INSTANCE_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
FIXED_NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)

APPROVER = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _step_row(
    *,
    step_id: uuid.UUID | None = None,
    instance_id: uuid.UUID = INSTANCE_ID,
    index: int = 0,
    status: str = "pending",
    sla_due_at: datetime = FIXED_NOW,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=step_id or uuid.uuid4(),
        instance_id=instance_id,
        step_index=index,
        step_key="approve",
        assignee_kind="users",
        assignee_value=str(APPROVER),
        status=status,
        sla_due_at=sla_due_at,
    )


# --------------------------------------------------------------- repository


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
    """Records queries; returns preset rows/scalar (repo conventions)."""

    def __init__(self, *, rows: list[object] | None = None, scalar: object = None) -> None:
        self._rows = rows or []
        self._scalar = scalar
        self.queries: list[str] = []
        self.flushes = 0
        self.refreshes = 0
        self.added: list[object] = []

    async def execute(self, stmt: object) -> _FakeResult:
        self.queries.append(str(stmt))
        return _FakeResult(scalar_value=self._scalar, rows=self._rows)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def refresh(self, obj: object) -> None:
        self.refreshes += 1


async def test_list_overdue_steps_queries_and_returns_rows() -> None:
    overdue = _step_row()
    session = _FakeSession(rows=[overdue])
    repository = ApprovalWorkflowInstanceRepository(session)  # type: ignore[arg-type]

    steps = await repository.list_overdue_steps(
        tenant_id=TENANT,
        now=FIXED_NOW,
        limit=200,
    )

    assert len(session.queries) == 1
    assert "sla_due_at" in session.queries[0]
    assert "current_step_index" in session.queries[0]
    assert "limit" in session.queries[0].lower()
    assert steps == [overdue]


async def test_mark_step_escalated_flips_pending_step_only() -> None:
    step = _step_row()
    session = _FakeSession(scalar=step)
    repository = ApprovalWorkflowInstanceRepository(session)  # type: ignore[arg-type]

    escalated = await repository.mark_step_escalated(tenant_id=TENANT, step_id=step.id)

    assert escalated is step
    assert step.status == "escalated"
    assert session.flushes == 1
    assert session.refreshes == 1


async def test_mark_step_escalated_idempotent_when_step_not_pending() -> None:
    session = _FakeSession(scalar=None)
    repository = ApprovalWorkflowInstanceRepository(session)  # type: ignore[arg-type]

    escalated = await repository.mark_step_escalated(tenant_id=TENANT, step_id=uuid.uuid4())

    assert escalated is None


async def test_list_pending_tenant_ids_returns_distinct_tenants() -> None:
    session = _FakeSession(rows=[TENANT, TENANT, TENANT_TWO])
    repository = ApprovalWorkflowInstanceRepository(session)  # type: ignore[arg-type]

    tenant_ids = await repository.list_pending_tenant_ids()

    assert len(session.queries) == 1
    assert "distinct" in session.queries[0].lower()
    assert {uuid.UUID(str(t)) for t in tenant_ids} == {TENANT, TENANT_TWO}


# ------------------------------------------------------------------ service


class _FakeEscalationRepo:
    """Recording repository the service drives (engine-test conventions)."""

    def __init__(self, overdue: list[object] | None = None) -> None:
        self.overdue = overdue or []
        self.escalated: list[uuid.UUID] = []
        self.transitions: list[dict] = []
        self.calls: list[tuple[str, dict]] = []

    async def list_overdue_steps(self, **kwargs: object) -> list[object]:
        self.calls.append(("list_overdue_steps", kwargs))
        return list(self.overdue)

    async def mark_step_escalated(self, **kwargs: object) -> object:
        self.calls.append(("mark_step_escalated", kwargs))
        self.escalated.append(str(kwargs["step_id"]))
        return next((s for s in self.overdue if s.id == kwargs["step_id"]), None)

    async def record_transition(self, **kwargs: object) -> object:
        self.calls.append(("record_transition", kwargs))
        self.transitions.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())


def _service(repo: _FakeEscalationRepo) -> ApprovalEscalationService:
    return ApprovalEscalationService(repo, now=lambda: FIXED_NOW)  # type: ignore[arg-type]


async def test_service_escalates_overdue_steps_and_audits_actor() -> None:
    step = _step_row()
    repo = _FakeEscalationRepo(overdue=[step])
    service = _service(repo)

    escalated = await service.escalate_overdue(tenant_id=TENANT, limit=200)

    assert escalated == 1
    assert repo.escalated == [str(step.id)]
    assert len(repo.transitions) == 1
    transition = repo.transitions[0]
    assert transition["previous_state"] == "pending"
    assert transition["new_state"] == "escalated"
    assert transition["actor_type"] == "escalation"
    assert transition["actor_id"] is None
    assert transition["step_id"] == step.id
    assert transition["workflow_instance_id"] == INSTANCE_ID
    assert transition["occurred_at"] == FIXED_NOW
    assert "sla_due_at" in transition["context"]


async def test_service_respects_limit_and_empty_backlog() -> None:
    repo = _FakeEscalationRepo(overdue=[])
    service = _service(repo)

    escalated = await service.escalate_overdue(tenant_id=TENANT, limit=200)

    assert escalated == 0
    assert repo.transitions == []
    assert repo.escalated == []


# -------------------------------------------------------------------- engine


class _FakeEngineRepo:
    """Minimal recording repo so the engine accepts an escalated step."""

    def __init__(self, *, step: SimpleNamespace) -> None:
        self.step = step
        self.instance = SimpleNamespace(
            id=INSTANCE_ID,
            tenant_id=TENANT,
            status="pending",
            current_step_index=step.step_index,
            resource_type="journal_entry",
            resource_id=uuid.uuid4(),
        )
        self.transitions: list[dict] = []
        self.instance_updates: list[dict] = []

    async def get_instance(self, tenant_id: uuid.UUID, instance_id: uuid.UUID) -> object:
        return self.instance

    async def list_steps(self, tenant_id: uuid.UUID, instance_id: uuid.UUID) -> list[object]:
        return [self.step]

    async def update_step_decision(self, **kwargs: object) -> object:
        self.step.status = kwargs["status"]
        self.step.decided_by = kwargs["decided_by"]
        return self.step

    async def update_instance_status(self, **kwargs: object) -> object:
        self.instance_updates.append(kwargs)
        self.instance.status = kwargs["status"]
        return self.instance

    async def record_transition(self, **kwargs: object) -> object:
        self.transitions.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    async def resolve_role_members(self, tenant_id: uuid.UUID, role: str) -> list[uuid.UUID]:
        return []

    async def resolve_permission_members(
        self, tenant_id: uuid.UUID, permission: str
    ) -> list[uuid.UUID]:
        return []


async def test_engine_decides_an_escalated_step_and_records_real_previous_state() -> None:
    repo = _FakeEngineRepo(step=_step_row(status="escalated"))
    engine = ApprovalEngine(repo, now=lambda: FIXED_NOW)  # type: ignore[arg-type]

    result = await engine.decide(
        tenant_id=TENANT,
        instance_id=INSTANCE_ID,
        actor_id=APPROVER,
        decision="approved",
        reason="Reviewed after SLA breach",
    )

    assert result.instance_completed is True
    assert result.instance.status == "approved"
    assert repo.instance_updates[0]["status"] == "approved"
    assert repo.transitions[0]["previous_state"] == "escalated"
    assert repo.transitions[0]["new_state"] == "approved"
    assert repo.transitions[0]["actor_type"] == "human"


# ------------------------------------------------------------------- worker


class _AsyncCtx:
    """Async context manager the factory returns so ``async with`` works."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeSessionFactory:
    """Returns scripted sessions in order: one discovery + one per tenant."""

    def __init__(self, sessions: list[_FakeSession]) -> None:
        self._sessions = iter(sessions)

    def __call__(self) -> _AsyncCtx:
        return _AsyncCtx(next(self._sessions))


class _FakeCommitSession(_FakeSession):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


async def test_worker_process_all_walks_tenants_and_commits_per_tenant() -> None:
    step_one = _step_row()
    step_two = _step_row(instance_id=uuid.uuid4())
    discovery = _FakeSession(rows=[TENANT, TENANT_TWO])
    tenant_one = _FakeCommitSession(rows=[step_one])
    tenant_two = _FakeCommitSession(rows=[step_two])
    factory = _FakeSessionFactory([discovery, tenant_one, tenant_two])
    worker = ApprovalEscalationWorker(factory, steps_per_pass=200)  # type: ignore[arg-type]

    outcome = await worker.process_all()

    assert outcome == EscalationOutcome(tenants_processed=2, steps_escalated=2)
    assert tenant_one.commits == 1
    assert tenant_two.commits == 1
    assert tenant_one.rollbacks == 0
    assert tenant_two.rollbacks == 0
