"""Unit tests for the restock-advisor demo agent (SKY-59 / SKY-68 touch).

These run the REAL ``ai_agent.features.restock_agent.graph`` through the real
runtime against an ``InMemorySaver`` — so the demo's read gate, the
interrupt/pause, the approval persistence (SuggestionRepository +
ai.suggestion.created audit) and the write-failure capture are all exercised
with real LangGraph semantics. Only the session (ledger/suggestion writes)
and the runtime's injected audit repo are fakes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from ai_agent.core.audit_events import AI_SUGGESTION_CREATED
from ai_agent.core.audit_service import AuditService
from ai_agent.features.restock_agent.graph import build_graph as restock_build_graph
from ai_agent.graphs.interrupts import InterruptRepository
from ai_agent.graphs.runtime import AgentDeployment, AgentDeps, AgentRuntime
from ai_agent.graphs.security import PERM_INVENTORY_AI_APPROVE, PERM_INVENTORY_READ
from ai_agent.models.agent_interrupt import AgentInterruptModel
from ai_agent.models.ai_suggestion import AiSuggestionModel

TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
REVIEWER_ID = uuid.uuid4()
AGENT_NAME = "restock_advisor"
AGENT = AgentDeployment(
    module="ai_agent.features.restock_agent.graph",
    tools=frozenset({"query_stock", "draft_suggestion", "apply_suggestion"}),
)

PRODUCT_ID = "11111111-1111-1111-1111-111111111111"
WAREHOUSE_ID = "22222222-2222-2222-2222-222222222222"
# current 2, reorder 5 -> suggested = max(2*5 - 2, 5) = 8 (deterministic formula).
INVOKE_PAYLOAD: dict[str, object] = {
    "product_id": PRODUCT_ID,
    "warehouse_id": WAREHOUSE_ID,
    "current_stock": 2,
    "reorder_point": 5,
}


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


class _LedgerSession:
    """Fake session: execute returns the created ledger row (decision-update
    select/rowcount shapes don't matter); add records every persisted row so
    the tests can inspect the suggestion + audit writes."""

    def __init__(self) -> None:
        self.executed: list[object] = []
        self.added: list[object] = []
        self._ledger: AgentInterruptModel | None = None

    async def execute(self, statement: object) -> _FakeResult:
        self.executed.append(statement)
        return _FakeResult([self._ledger] if self._ledger else [], rowcount=1)

    def add(self, obj: object) -> None:
        if isinstance(obj, AgentInterruptModel):
            self._ledger = obj
        self.added.append(obj)

    async def flush(self) -> None:
        return None


class _FakeAuditRepo:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object] | None]] = []

    async def add(self, **kwargs: Any) -> Any:
        self.events.append((kwargs["action"], kwargs.get("input_payload")))
        return None


def build_restock_graph(deps: AgentDeps, module: str) -> Any:
    """Slot the demo's 1-arg build_graph(deps) into the runtime's 2-arg slot."""
    return restock_build_graph(deps)


def _audit_action_payload(audit: _FakeAuditRepo, action: str) -> dict[str, object] | None:
    """The input payload recorded for one audit action (or None)."""
    for event_action, payload in audit.events:
        if event_action == action:
            return payload
    return None


def make_runtime(
    *,
    permissions: list[str] | None = None,
    suggestions: Any = None,
) -> tuple[AgentRuntime, _LedgerSession, _FakeAuditRepo]:
    audit_repo = _FakeAuditRepo()
    ledger = _LedgerSession()

    async def resolve_deployment(name: str) -> AgentDeployment:
        if name != AGENT_NAME:
            from skyrict_common.exceptions import NotFoundError

            raise NotFoundError(f"Agent not available: {name}")
        return AGENT

    async def resolve_permissions(user_id: uuid.UUID, tenant_id: uuid.UUID) -> list[str]:
        return permissions or [PERM_INVENTORY_AI_APPROVE, PERM_INVENTORY_READ]

    runtime = AgentRuntime(
        session=ledger,  # type: ignore[arg-type]
        checkpointer=InMemorySaver(),  # type: ignore[arg-type]
        resolve_deployment=resolve_deployment,
        resolve_permissions=resolve_permissions,
        build_graph=build_restock_graph,
        interrupts=InterruptRepository(ledger),  # type: ignore[arg-type]
        audit=AuditService(audit_repo),  # type: ignore[arg-type]
        suggestions=suggestions,  # type: ignore[arg-type]
    )
    return runtime, ledger, audit_repo


async def test_invoke_reads_snapshot_and_pauses_for_review() -> None:
    runtime, ledger, _ = make_runtime()

    outcome = await runtime.invoke(
        agent_name=AGENT_NAME,
        input_payload=INVOKE_PAYLOAD,
        user_id=USER_ID,
        tenant_id=TENANT_ID,
    )

    assert outcome.status == "awaiting_decision"
    assert outcome.interrupt is not None
    assert outcome.interrupt.status == "pending"
    assert outcome.interrupt.tool == "apply_suggestion"
    assert outcome.interrupt.payload["required_permission"] == PERM_INVENTORY_AI_APPROVE
    payload = outcome.interrupt.payload["payload"]
    assert payload["product_id"] == PRODUCT_ID
    assert payload["warehouse_id"] == WAREHOUSE_ID
    assert payload["suggested_qty"] == 8
    assert "reorder" in str(payload["reason"])
    assert len(ledger.added) == 1  # one pending interrupt, nothing decided


async def test_approve_persists_suggestion_and_audits_created() -> None:
    runtime, ledger, audit = make_runtime()
    first = await runtime.invoke(
        agent_name=AGENT_NAME, input_payload=INVOKE_PAYLOAD, user_id=USER_ID, tenant_id=TENANT_ID
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

    suggestions = [row for row in ledger.added if isinstance(row, AiSuggestionModel)]
    assert len(suggestions) == 1
    assert suggestions[0].tenant_id == TENANT_ID
    assert suggestions[0].status == "pending"
    assert suggestions[0].suggested_qty == Decimal("8")
    assert suggestions[0].product_id == uuid.UUID(PRODUCT_ID)

    # The runtime's injected audit port carries the suggestion-created event.
    created = _audit_action_payload(audit, AI_SUGGESTION_CREATED)
    assert created is not None
    assert created["suggestion_id"] == str(suggestions[0].id)

    # The runtime ALSO audits the interrupt decision through the same port.
    assert any(action == "ai.agent.interrupt.approved" for action, _ in audit.events)


async def test_deny_is_a_clean_noop() -> None:
    runtime, ledger, audit = make_runtime()
    first = await runtime.invoke(
        agent_name=AGENT_NAME, input_payload=INVOKE_PAYLOAD, user_id=USER_ID, tenant_id=TENANT_ID
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
    # Nothing was persisted: no suggestion row, no suggestion-created audit.
    assert not any(isinstance(row, AiSuggestionModel) for row in ledger.added)
    assert _audit_action_payload(audit, AI_SUGGESTION_CREATED) is None
    assert any(action == "ai.agent.interrupt.denied" for action, _ in audit.events)


async def test_invoke_without_read_permission_fails_with_permission_denied() -> None:
    # The approver role alone cannot even start the demo: query_stock enforces
    # the read gate inside the graph, and the runtime sanitizes it.
    runtime, ledger, _ = make_runtime(permissions=[PERM_INVENTORY_AI_APPROVE])

    outcome = await runtime.invoke(
        agent_name=AGENT_NAME,
        input_payload=INVOKE_PAYLOAD,
        user_id=USER_ID,
        tenant_id=TENANT_ID,
    )

    assert outcome.status == "failed"
    assert outcome.output == {"error": "permission_denied"}
    assert len(ledger.added) == 0  # no interrupt was ever opened


async def test_approve_with_write_failure_is_captured_in_state() -> None:
    """The decision commits (decision-first), but the apply write failure is
    captured into state — never raised into the checkpoint."""

    class _FailingSuggestions:
        def __init__(self, session: object) -> None:
            pass

        async def create_pending(self, **kwargs: Any) -> AiSuggestionModel:
            raise RuntimeError("database gone")

    runtime, ledger, audit = make_runtime(suggestions=_FailingSuggestions(object()))
    first = await runtime.invoke(
        agent_name=AGENT_NAME, input_payload=INVOKE_PAYLOAD, user_id=USER_ID, tenant_id=TENANT_ID
    )
    assert first.interrupt is not None

    outcome = await runtime.resume(
        agent_name=AGENT_NAME,
        interrupt_id=first.interrupt.id,
        decision="approved",
        decided_by=REVIEWER_ID,
        note=None,
        user_id=USER_ID,
        tenant_id=TENANT_ID,
    )

    assert outcome.status == "completed"
    assert outcome.output is not None
    assert outcome.output["applied"] is False
    assert outcome.output["outcome"] == "write_failed"
    assert first.interrupt.status == "approved"
    assert not any(isinstance(row, AiSuggestionModel) for row in ledger.added)
    assert _audit_action_payload(audit, AI_SUGGESTION_CREATED) is None


async def test_lazy_expiry_still_denies_the_demo_interrupt() -> None:
    """The demo runs through the runtime, so the 24h lazy expiry applies."""
    runtime, ledger, audit = make_runtime()
    first = await runtime.invoke(
        agent_name=AGENT_NAME, input_payload=INVOKE_PAYLOAD, user_id=USER_ID, tenant_id=TENANT_ID
    )
    assert first.interrupt is not None
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
    assert any(action == "ai.agent.interrupt.expired" for action, _ in audit.events)
    # The demo never reached its apply node, so no suggestion writes.
    assert not any(isinstance(row, AiSuggestionModel) for row in ledger.added)
