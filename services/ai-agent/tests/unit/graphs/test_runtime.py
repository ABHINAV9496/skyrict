"""Unit tests for the agent runtime (SKY-59).

These run a REAL LangGraph (draft -> interrupt -> apply) against an
``InMemorySaver`` - so the checkpointed pause/resume semantics are exercised,
not faked. Only the session (ledger/RLS) and the audit repo are fakes; the
interrupt contract (tool + permission + payload) flows through the actual
runtime gate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from typing_extensions import TypedDict

from ai_agent.core.audit_events import (
    AI_AGENT_INTERRUPT_APPROVED,
    AI_AGENT_INTERRUPT_DENIED,
    AI_AGENT_INTERRUPT_EXPIRED,
)
from ai_agent.core.audit_service import AuditService
from ai_agent.graphs.interrupts import InterruptRepository
from ai_agent.graphs.runtime import AgentDeployment, AgentDeps, AgentRuntime, RunOutcome
from ai_agent.graphs.security import PERM_INVENTORY_AI_APPROVE, PERM_INVENTORY_READ
from ai_agent.models.agent_interrupt import AgentInterruptModel
from skyrict_common.exceptions import ConflictError, NotFoundError, PermissionDeniedError

TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
REVIEWER_ID = uuid.uuid4()
AGENT_NAME = "restock_advisor"
AGENT = AgentDeployment(module="demo.restock", tools=frozenset({PERM_INVENTORY_AI_APPROVE}))


class DemoState(TypedDict, total=False):
    draft: dict[str, object]
    applied: bool
    outcome: str


def _draft_node(state: DemoState) -> dict[str, object]:
    return {"draft": {"product_id": "P1", "qty": 3}}


def _approval_node(state: DemoState) -> dict[str, object]:
    """The demo's human-in-the-loop gate (side-effect-free before interrupt)."""
    decision = interrupt(
        {
            "tool": "apply_suggestion",
            "required_permission": PERM_INVENTORY_AI_APPROVE,
            "payload": state["draft"],
        }
    )
    if decision["decision"] == "approved":
        return {"applied": True, "outcome": "applied"}
    return {"applied": False, "outcome": "denied"}


def build_demo_graph(deps: AgentDeps, module: str) -> Any:
    """The fictitious demo module contract: build_graph(deps, module) -> uncompiled graph."""
    builder = StateGraph(DemoState)
    builder.add_node("draft", _draft_node)
    builder.add_node("approval", _approval_node)
    builder.add_edge(START, "draft")
    builder.add_edge("draft", "approval")
    builder.add_edge("approval", END)
    return builder


class _FakeResult:
    def __init__(self, rows: list[object] | None = None, rowcount: int = 1) -> None:
        self._rows = rows or []
        self._rowcount = rowcount

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[object]:
        return self._rows

    def scalar_one_or_none(self) -> object | None:
        return self._rows[0] if self._rows else None

    @property
    def rowcount(self) -> int:
        return self._rowcount


class _FakeSession:
    def __init__(self, result: list[object] | None = None, rowcount: int = 1) -> None:
        self.result = result
        self.rowcount = rowcount
        self.executed: list[object] = []
        self.added: list[AgentInterruptModel] = []

    async def execute(self, statement: object) -> _FakeResult:
        self.executed.append(statement)
        return _FakeResult(self.result, self.rowcount)

    def add(self, obj: AgentInterruptModel) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


class _FakeAuditRepo:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object] | None]] = []

    async def add(self, **kwargs: Any) -> Any:
        self.events.append((kwargs["action"], kwargs.get("input_payload")))
        return None


class _LedgerSession(_FakeSession):
    """Fake session: every execute returns the created ledger row (the
    decision-update select/rowcount shapes don't matter to these tests)."""

    def __init__(self) -> None:
        super().__init__(result=[])
        self._created: AgentInterruptModel | None = None

    async def execute(self, statement: object) -> _FakeResult:
        self.executed.append(statement)
        return _FakeResult([self._created] if self._created else [], rowcount=1)

    def add(self, obj: AgentInterruptModel) -> None:
        self._created = obj
        self.added.append(obj)


def make_runtime(
    session: _FakeSession | None = None,
    *,
    permissions: list[str] | None = None,
    graph_builder: Any = None,
    ledger: _LedgerSession | None = None,
) -> tuple[AgentRuntime, _FakeAuditRepo]:
    audit_repo = _FakeAuditRepo()
    fake_session = ledger or session or _FakeSession()

    async def resolve_deployment(name: str) -> AgentDeployment:
        if name != AGENT_NAME:
            raise NotFoundError(f"Agent not available: {name}")
        return AGENT

    async def resolve_permissions(user_id: uuid.UUID, tenant_id: uuid.UUID) -> list[str]:
        return permissions or [PERM_INVENTORY_AI_APPROVE, PERM_INVENTORY_READ]

    runtime = AgentRuntime(
        session=fake_session,  # type: ignore[arg-type]
        checkpointer=InMemorySaver(),  # type: ignore[arg-type]
        resolve_deployment=resolve_deployment,
        resolve_permissions=resolve_permissions,
        build_graph=graph_builder or build_demo_graph,
        interrupts=InterruptRepository(fake_session),  # type: ignore[arg-type]
        audit=AuditService(audit_repo),  # type: ignore[arg-type]
    )
    return runtime, audit_repo


async def test_invoke_pauses_with_pending_ledger() -> None:
    ledger = _LedgerSession()
    runtime, _ = make_runtime(ledger=ledger)

    outcome = await runtime.invoke(
        agent_name=AGENT_NAME,
        input_payload={},
        user_id=USER_ID,
        tenant_id=TENANT_ID,
    )

    assert outcome.status == "awaiting_decision"
    assert outcome.interrupt is not None
    assert outcome.interrupt.status == "pending"
    assert outcome.interrupt.agent_name == AGENT_NAME
    assert outcome.interrupt.tool == "apply_suggestion"
    assert outcome.interrupt.payload["required_permission"] == PERM_INVENTORY_AI_APPROVE
    assert outcome.interrupt.payload["payload"] == {"product_id": "P1", "qty": 3}
    # One ledger row exists, nothing decided.
    assert len(ledger.added) == 1


async def test_resume_approval_applies_and_completes() -> None:
    ledger = _LedgerSession()
    runtime, audit = make_runtime(ledger=ledger)
    first = await runtime.invoke(
        agent_name=AGENT_NAME, input_payload={}, user_id=USER_ID, tenant_id=TENANT_ID
    )
    assert first.interrupt is not None

    outcome = await runtime.resume(
        agent_name=AGENT_NAME,
        interrupt_id=first.interrupt.id,
        decision="approved",
        decided_by=REVIEWER_ID,
        note="looks good",
        user_id=USER_ID,
        tenant_id=TENANT_ID,
    )

    assert outcome.status == "completed"
    assert outcome.output is not None
    assert outcome.output["applied"] is True
    assert outcome.output["outcome"] == "applied"
    assert first.interrupt.status == "approved"
    assert first.interrupt.decided_by == REVIEWER_ID
    assert _audit_action_payload(audit, AI_AGENT_INTERRUPT_APPROVED) == {
        "graph_run_id": str(first.graph_run_id),
        "interrupt_id": str(first.interrupt.id),
    }


async def test_resume_denial_noops_and_completes() -> None:
    ledger = _LedgerSession()
    runtime, audit = make_runtime(ledger=ledger)
    first = await runtime.invoke(
        agent_name=AGENT_NAME, input_payload={}, user_id=USER_ID, tenant_id=TENANT_ID
    )
    assert first.interrupt is not None

    outcome = await runtime.resume(
        agent_name=AGENT_NAME,
        interrupt_id=first.interrupt.id,
        decision="denied",
        decided_by=REVIEWER_ID,
        note="no",
        user_id=USER_ID,
        tenant_id=TENANT_ID,
    )

    assert outcome.status == "completed"
    assert outcome.output is not None
    assert outcome.output["applied"] is False
    assert outcome.output["outcome"] == "denied"
    assert first.interrupt.status == "denied"
    assert first.interrupt.decided_by == REVIEWER_ID
    assert _audit_action_payload(audit, AI_AGENT_INTERRUPT_DENIED) is not None


async def test_double_approval_is_refused() -> None:
    ledger = _LedgerSession()
    runtime, _ = make_runtime(ledger=ledger)
    first = await runtime.invoke(
        agent_name=AGENT_NAME, input_payload={}, user_id=USER_ID, tenant_id=TENANT_ID
    )
    assert first.interrupt is not None
    await runtime.resume(
        agent_name=AGENT_NAME,
        interrupt_id=first.interrupt.id,
        decision="approved",
        decided_by=REVIEWER_ID,
        note=None,
        user_id=USER_ID,
        tenant_id=TENANT_ID,
    )

    with pytest.raises(ConflictError):
        await runtime.resume(
            agent_name=AGENT_NAME,
            interrupt_id=first.interrupt.id,
            decision="approved",
            decided_by=REVIEWER_ID,
            note=None,
            user_id=USER_ID,
            tenant_id=TENANT_ID,
        )


async def test_invoke_without_tool_permission_is_denied() -> None:
    runtime, _ = make_runtime(permissions=[PERM_INVENTORY_READ])

    with pytest.raises(PermissionDeniedError):
        await runtime.invoke(
            agent_name=AGENT_NAME, input_payload={}, user_id=USER_ID, tenant_id=TENANT_ID
        )


async def test_invoke_unknown_agent_is_not_found() -> None:
    runtime, _ = make_runtime()

    with pytest.raises(NotFoundError):
        await runtime.invoke(
            agent_name="ghost", input_payload={}, user_id=USER_ID, tenant_id=TENANT_ID
        )


async def test_resume_rejects_wrong_agent_name() -> None:
    ledger = _LedgerSession()
    runtime, _ = make_runtime(ledger=ledger)
    first = await runtime.invoke(
        agent_name=AGENT_NAME, input_payload={}, user_id=USER_ID, tenant_id=TENANT_ID
    )
    assert first.interrupt is not None

    with pytest.raises(NotFoundError):
        await runtime.resume(
            agent_name="other_agent",
            interrupt_id=first.interrupt.id,
            decision="approved",
            decided_by=REVIEWER_ID,
            note=None,
            user_id=USER_ID,
            tenant_id=TENANT_ID,
        )


async def test_lazy_expiry_auto_denies_stale_pending() -> None:
    ledger = _LedgerSession()
    runtime, audit = make_runtime(ledger=ledger)
    first = await runtime.invoke(
        agent_name=AGENT_NAME, input_payload={}, user_id=USER_ID, tenant_id=TENANT_ID
    )
    assert first.interrupt is not None
    # The 24h window passed while the reviewer was away.
    first.interrupt.expires_at = datetime.now(tz=UTC) - timedelta(hours=1)

    outcome = await runtime.resume(
        agent_name=AGENT_NAME,
        interrupt_id=first.interrupt.id,
        decision="approved",
        decided_by=REVIEWER_ID,
        note=None,
        user_id=USER_ID,
        tenant_id=TENANT_ID,
    )

    assert outcome.status == "failed"
    assert outcome.output == {"error": "interrupt_expired"}
    assert first.interrupt.status == "denied"
    assert first.interrupt.decided_by is None  # no human decided - the clock did
    assert any(action == AI_AGENT_INTERRUPT_EXPIRED for action, _ in audit.events)


async def test_list_pending_returns_queue() -> None:
    session = _FakeSession([_pending_row(), _pending_row()])
    runtime, _ = make_runtime(session=session)

    rows = await runtime.list_pending(tenant_id=TENANT_ID)

    assert len(rows) == 2


def _pending_row() -> AgentInterruptModel:
    return AgentInterruptModel(
        tenant_id=TENANT_ID,
        id=uuid.uuid4(),
        graph_run_id=uuid.uuid4(),
        agent_name=AGENT_NAME,
        tool="apply_suggestion",
        payload={"tool": "apply_suggestion"},
        status="pending",
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        created_at=datetime.now(tz=UTC),
    )


def _audit_action_payload(audit: _FakeAuditRepo, action: str) -> dict[str, object] | None:
    """The input payload recorded for one audit action (or None)."""
    for event_action, payload in audit.events:
        if event_action == action:
            return payload
    return None


async def test_completed_outcome_returns_state() -> None:
    session = _FakeSession()
    runtime, _ = make_runtime(
        session=session,
        graph_builder=_build_plain_graph,
    )

    outcome: RunOutcome = await runtime.invoke(
        agent_name=AGENT_NAME, input_payload={}, user_id=USER_ID, tenant_id=TENANT_ID
    )

    assert outcome.status == "completed"
    assert outcome.output is not None
    assert outcome.output["outcome"] == "done"
    assert outcome.interrupt is None


def _build_plain_graph(deps: AgentDeps, module: str) -> Any:
    """A graph with no interrupt - used to test the completed path."""

    def run(state: DemoState) -> dict[str, object]:
        return {"outcome": "done"}

    builder = StateGraph(DemoState)
    builder.add_node("run", run)
    builder.add_edge(START, "run")
    builder.add_edge("run", END)
    return builder
