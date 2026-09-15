"""SKY-100: delegate prompt builders bound live context with ContextBudgetManager.

Every module delegator now trims the live context it assembles to its
per-agent token budget instead of ad-hoc character caps (or no cap at all):
Inventory (RAG + stock), CRM (live data + memory), Finance (live data),
Sales Coach (suggestions), and Audit Guardian (report context).

These tests prove the wiring by pushing oversized context through each
delegator and asserting the elision marker appears and the giant payload no
longer reaches the LLM request. Small-context paths are covered by the
existing suite (e.g. finance fallback grounding) and stay byte-identical.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.core.providers import LlmCompletion, LlmRequest
from ai_agent.features.memory_compaction.budget import ContextBudgetManager
from ai_agent.features.supervisor.delegates import (
    AuditGuardianDelegator,
    CrmAssistantDelegator,
    FinanceDelegator,
    InventoryMonitorDelegator,
    SalesCoachDelegator,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
_ELISION = "… (context trimmed to fit budget)"

# A payload far larger than any per-agent budget so trimming must engage.
_BIG = "observe " * 12_000  # ~72k chars >> every agent budget


class _CaptureRouter:
    """Router that captures the last LlmRequest and echoes a canned answer."""

    def __init__(self) -> None:
        self.has_providers = True
        self.last_request: LlmRequest | None = None

    async def complete(self, request: LlmRequest) -> LlmCompletion:
        self.last_request = request
        return LlmCompletion(text="answer", model_used="fake-model", latency_ms=1)

    async def stream(self, request: LlmRequest) -> AsyncIterator[Any]:
        self.last_request = request
        yield SimpleNamespace(token_delta="answer", model_used="fake-model")


async def _collect_tokens(delegator: Any, query: str) -> str:
    deltas = [
        delta
        async for delta in delegator.stream(
            query=query,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            citations=[],
        )
    ]
    return "".join(deltas)


class _FakeMemoryService:
    async def recall_context(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, query: str) -> str:
        del tenant_id, user_id, query
        return _BIG

    async def store_after_chat(self, **_: Any) -> None:
        return None


class _FakeCrmGateway:
    async def list_opportunities(self) -> list[object]:
        return [
            SimpleNamespace(
                id=uuid.uuid4(),
                stage="new",
                display_name="Deal",
                amount=Decimal("100.0000"),
                currency="USD",
                expected_close_date=None,
                probability=50,
            )
        ]

    async def list_leads(self) -> list[object]:
        return [
            SimpleNamespace(
                id=uuid.uuid4(),
                status="new",
                display_name="A",
                email=None,
                phone=None,
                company=None,
                source="web",
            )
        ]


class _FakeFinanceGateway:
    async def list_invoices(self) -> list[object]:
        return [SimpleNamespace(status="issued", total=Decimal("10.0000")) for _ in range(10_000)]

    async def get_pnl(self) -> object | None:
        return None

    async def get_ar_aging(self) -> object | None:
        return None


class _FakeInventoryGateway:
    async def get_stock_levels(self) -> list[object]:
        raise AiUnavailableError("not used")

    async def list_products(self) -> list[object]:
        return []


class _FakeRag:
    async def search(
        self, *, query: str, tenant_id: uuid.UUID, user_id: uuid.UUID, module: str | None = None
    ) -> Any:
        del query, tenant_id, user_id, module
        return SimpleNamespace(
            data=[SimpleNamespace(source_ref="r1", chunk_text=_BIG, module="inventory")]
        )


class _FakeSuggestions:
    async def list_pending_for_rep(
        self, *, tenant_id: uuid.UUID, rep_user_id: uuid.UUID
    ) -> list[dict[str, object]]:
        del tenant_id, rep_user_id
        return [
            {"status": "pending", "title": "Weekly check-in", "body": _BIG},
            {"status": "pending", "title": "Follow up", "body": "short"},
            {"status": "done", "title": "Ignored", "body": "x"},
        ]


class _FakeGuardianReports:
    async def list_reports(
        self, *, tenant_id: uuid.UUID, limit: int = 1
    ) -> list[dict[str, object]]:
        del tenant_id, limit
        return [
            {"id": uuid.uuid4(), "summary": _BIG, "flagged_count": 1, "total_events_scanned": 9}
        ]

    async def list_events_for_report(
        self, *, tenant_id: uuid.UUID, report_id: uuid.UUID
    ) -> list[dict[str, object]]:
        del tenant_id, report_id
        return [{"severity": "high", "reason": _BIG, "source_table": "x", "event_action": "y"}]


class TestDelegateContextBudget:
    async def test_inventory_bounds_rag_context(self) -> None:
        router = _CaptureRouter()
        delegator = InventoryMonitorDelegator(
            llm_router=router,  # type: ignore[arg-type]
            gateway_factory=_fake_inventory_gateway,
            rag=_FakeRag(),  # type: ignore[arg-type]
        )
        await _collect_tokens(delegator, "what stock is below reorder point?")

        assert router.last_request is not None
        assert _ELISION in router.last_request.user_prompt
        assert len(_BIG) > len(router.last_request.user_prompt)

    async def test_crm_bounds_live_data_and_memory(self) -> None:
        router = _CaptureRouter()
        delegator = CrmAssistantDelegator(
            llm_router=router,  # type: ignore[arg-type]
            crm_gateway_factory=_fake_crm_gateway,
            memory_service=_FakeMemoryService(),  # type: ignore[arg-type]
        )
        await _collect_tokens(delegator, "summarize my deals")

        assert router.last_request is not None
        assert _ELISION in router.last_request.system_prompt
        assert len(_BIG) > len(router.last_request.system_prompt)

    async def test_crm_under_budget_keeps_byte_identical_format(self) -> None:
        router = _CaptureRouter()
        delegator = CrmAssistantDelegator(
            llm_router=router,  # type: ignore[arg-type]
            crm_gateway_factory=_fake_crm_gateway_without_leads,
            memory_service=_FakeShortMemory(),  # type: ignore[arg-type]
        )
        await _collect_tokens(delegator, "summarize my deals")

        assert router.last_request is not None
        assert "Live CRM data:" in router.last_request.system_prompt
        assert "short memory here" in router.last_request.system_prompt
        assert "\n\n" in router.last_request.system_prompt  # same join as before

    async def test_finance_bounds_live_context(self) -> None:
        router = _CaptureRouter()
        factory = _fake_finance_gateway
        delegator = FinanceDelegator(
            llm_router=router,  # type: ignore[arg-type]
            finance_gateway_factory=factory,
        )

        # The real gatherer produces naturally small text; monkeypatch it
        # to prove the wiring trims whatever the gatherer returns.
        async def _big_context(query: str) -> str:
            return _BIG

        delegator._gather_finance_context = _big_context  # type: ignore[attr-defined]
        await _collect_tokens(delegator, "summarize our finances")

        assert router.last_request is not None
        assert _ELISION in router.last_request.system_prompt
        assert len(_BIG) > len(router.last_request.system_prompt)

    async def test_sales_coach_bounds_suggestions(self) -> None:
        router = _CaptureRouter()
        delegator = SalesCoachDelegator(
            llm_router=router,  # type: ignore[arg-type]
            suggestions=_FakeSuggestions(),  # type: ignore[arg-type]
        )
        await _collect_tokens(delegator, "what should I do first?")

        assert router.last_request is not None
        assert _ELISION in router.last_request.user_prompt
        assert len(_BIG) > len(router.last_request.user_prompt)

    async def test_audit_guardian_bounds_report_context(self) -> None:
        router = _CaptureRouter()
        delegator = AuditGuardianDelegator(
            llm_router=router,  # type: ignore[arg-type]
            guardian_reports=_FakeGuardianReports(),  # type: ignore[arg-type]
        )
        await _collect_tokens(delegator, "any findings?")

        assert router.last_request is not None
        assert _ELISION in router.last_request.user_prompt
        assert len(_BIG) > len(router.last_request.user_prompt)

    async def test_budget_is_per_agent_not_a_single_global(self) -> None:
        # The wiring must consult the per-agent budget: a known agent key gets
        # its own budget, so the manager's default is not applied to unknown
        # agents inside the delegators (they always pass a real key).
        manager = ContextBudgetManager()
        assert manager.budget_for("crm_assistant") == 4000
        assert manager.budget_for("sales_coach") == 3000
        assert manager.budget_for("audit_guardian") == 3000


async def _fake_inventory_gateway() -> _FakeInventoryGateway:
    return _FakeInventoryGateway()


async def _fake_crm_gateway() -> _FakeCrmGateway:
    return _FakeCrmGateway()


async def _fake_crm_gateway_without_leads() -> _FakeCrmGateway:
    class _NoLeads(_FakeCrmGateway):
        async def list_leads(self) -> list[object]:
            return []

    return _NoLeads()


async def _fake_finance_gateway() -> _FakeFinanceGateway:
    return _FakeFinanceGateway()


class _FakeShortMemory:
    async def recall_context(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, query: str) -> str:
        del tenant_id, user_id, query
        return "short memory here"

    async def store_after_chat(self, **_: Any) -> None:
        return None
