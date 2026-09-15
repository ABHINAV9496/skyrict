"""SKY-100 supervisor caches: classification, response, and tool caching.

Covers:
- classification cache hit skips the provider call and still applies the
  routing threshold; corrupt entries fall back to the provider;
- response cache skips repeated identical supervisor-answer turns, is tenant
  scoped, respects TTL expiry, and never engages for image payloads;
- CRM deterministic NL actions are cached per tenant; Finance deterministic
  summaries are cached per tenant;
- the no-tenant classification path stays uncached (existing behavior).
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import TYPE_CHECKING

from ai_agent.cache.response_cache import (
    MemoryResponseCache,
    classification_cache_key,
)
from ai_agent.core.providers import LlmCompletion, LlmRequest
from ai_agent.core.providers.base import LlmStreamChunk
from ai_agent.features.supervisor.delegates import (
    CrmAssistantDelegator,
    FinanceDelegator,
)
from ai_agent.features.supervisor.prompts import CLASSIFY_SYSTEM_PROMPT
from ai_agent.features.supervisor.schemas import (
    ClassificationEvent,
    SupervisorEvent,
    TokenEvent,
)
from ai_agent.features.supervisor.service import SupervisorService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
USER_ID = uuid.uuid4()

_CLASSIFY_ANSWER = '{"agents": ["inventory_monitor"], "confidence": 0.9}'
_ABSTAIN_ANSWER = '{"agents": [], "confidence": 0.1}'
_SUPERVISOR_ANSWER = (
    "Here is the supervisor answer for the cached response path. "
    "It is deliberately long enough to stream as several word deltas."
)


class FakeLlmRouter:
    """Scripted router: classifier JSON or supervisor answer by system prompt."""

    def __init__(
        self,
        *,
        classify_text: str = _CLASSIFY_ANSWER,
        has_providers: bool = True,
    ) -> None:
        self.has_providers = has_providers
        self._classify_text = classify_text
        self.complete_calls = 0
        self.stream_calls = 0

    @property
    def provider_calls(self) -> int:
        return self.complete_calls + self.stream_calls

    async def complete(self, request: LlmRequest) -> LlmCompletion:
        self.complete_calls += 1
        text = (
            self._classify_text
            if request.system_prompt == CLASSIFY_SYSTEM_PROMPT
            else _SUPERVISOR_ANSWER
        )
        return LlmCompletion(text=text, model_used="fake-model", latency_ms=1)

    async def stream(self, request: LlmRequest) -> AsyncIterator[LlmStreamChunk]:
        self.stream_calls += 1
        for delta in _word_deltas(_SUPERVISOR_ANSWER):
            yield LlmStreamChunk(token_delta=delta, model_used="fake-model")


class FakeGateway:
    async def list_products(self) -> list[object]:
        return []

    async def list_warehouses(self) -> list[object]:
        return []

    async def get_stock_levels(
        self,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
    ) -> list[object]:
        return []

    async def list_movements(
        self,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
        movement_type: str | None = None,
    ) -> list[object]:
        return []


class FakeCrmGateway:
    def __init__(self, leads: list[object] | None = None) -> None:
        self._leads = leads or [SimpleNamespace(status="new"), SimpleNamespace(status="new")]
        self.list_leads_calls = 0

    async def list_leads(self) -> list[object]:
        self.list_leads_calls += 1
        return self._leads


class FakeFinanceGateway:
    def __init__(self, invoices: list[object] | None = None) -> None:
        self._invoices = invoices or [
            SimpleNamespace(status="sent"),
            SimpleNamespace(status="sent"),
            SimpleNamespace(status="paid"),
        ]
        self.list_invoices_calls = 0

    async def list_invoices(self) -> list[object]:
        self.list_invoices_calls += 1
        return self._invoices


class FakeConversationHistory:
    def __init__(self, message_count: int = 1) -> None:
        self.get_messages_calls = 0
        self.last_limit: int | None = None
        self._messages = [
            {"role": "user", "content": f"message {index}"} for index in range(message_count)
        ]

    async def get_messages(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        limit: int | None = None,
    ) -> list[dict[str, str]]:
        del tenant_id, conversation_id
        self.get_messages_calls += 1
        self.last_limit = limit
        return self._messages


class RecordingSupervisorRouter(FakeLlmRouter):
    """Records the supervisor-answer prompt so tests can assert its contents."""

    def __init__(self) -> None:
        super().__init__(classify_text=_ABSTAIN_ANSWER)
        self.last_supervisor_prompt: str | None = None

    async def complete(self, request: LlmRequest) -> LlmCompletion:
        if request.system_prompt != CLASSIFY_SYSTEM_PROMPT:
            self.last_supervisor_prompt = request.system_prompt
        return await super().complete(request)


def make_service(
    *,
    router: FakeLlmRouter | None = None,
    classification_cache: MemoryResponseCache | None = None,
    response_cache: MemoryResponseCache | None = None,
    conversation_history: FakeConversationHistory | None = None,
    provisioned: dict[str, bool] | None = None,
) -> SupervisorService:
    gateway = FakeGateway()

    async def gateway_factory() -> FakeGateway:
        return gateway

    return SupervisorService(
        llm_router=router or FakeLlmRouter(),
        gateway_factory=gateway_factory,
        conversation_history=conversation_history,
        provisioned=provisioned or {"inventory_monitor": True},
        classification_cache=classification_cache,
        response_cache=response_cache,
        classification_cache_ttl_seconds=300,
        response_cache_ttl_seconds=300,
    )


def make_crm_delegate(
    *,
    router: FakeLlmRouter,
    gateway: FakeCrmGateway,
    tool_cache: MemoryResponseCache | None = None,
) -> CrmAssistantDelegator:
    async def gateway_factory() -> FakeCrmGateway:
        return gateway

    return CrmAssistantDelegator(
        llm_router=router,
        crm_gateway_factory=gateway_factory,
        memory_service=None,
        tool_cache=tool_cache,
        tool_cache_ttl_seconds=60,
    )


def make_finance_delegate(
    *,
    router: FakeLlmRouter,
    gateway: FakeFinanceGateway,
    tool_cache: MemoryResponseCache | None = None,
) -> FinanceDelegator:
    async def gateway_factory() -> FakeFinanceGateway:
        return gateway

    return FinanceDelegator(
        llm_router=router,
        finance_gateway_factory=gateway_factory,
        tool_cache=tool_cache,
        tool_cache_ttl_seconds=60,
    )


async def collect(service: SupervisorService, query: str) -> list[SupervisorEvent]:
    return [
        event
        async for event in service.stream_answer(query=query, tenant_id=TENANT_A, user_id=USER_ID)
    ]


def tokens_text(events: list[SupervisorEvent]) -> str:
    return "".join(e.delta for e in events if isinstance(e, TokenEvent))


def _word_deltas(text: str) -> list[str]:
    words = text.split(" ")
    return [word + (" " if index < len(words) - 1 else "") for index, word in enumerate(words)]


# --- classification cache ---------------------------------------------------


async def test_classification_cache_hit_skips_provider() -> None:
    router = FakeLlmRouter()
    cache = MemoryResponseCache()
    service = make_service(router=router, classification_cache=cache)

    first = await service.classify("What stock is below reorder point?", tenant_id=TENANT_A)
    second = await service.classify("What stock is below reorder point?", tenant_id=TENANT_A)

    assert first.agents == ("inventory_monitor",)
    assert second == first
    assert router.complete_calls == 1


async def test_classification_cache_is_tenant_scoped() -> None:
    router = FakeLlmRouter()
    service = make_service(router=router, classification_cache=MemoryResponseCache())

    await service.classify("What stock is below reorder point?", tenant_id=TENANT_A)
    await service.classify("What stock is below reorder point?", tenant_id=TENANT_B)

    assert router.complete_calls == 2


async def test_classification_without_tenant_is_never_cached() -> None:
    router = FakeLlmRouter()
    service = make_service(router=router, classification_cache=MemoryResponseCache())

    await service.classify("What stock is below reorder point?")
    await service.classify("What stock is below reorder point?")

    assert router.complete_calls == 2


async def test_cached_classification_still_obeys_threshold() -> None:
    router = FakeLlmRouter()
    cache = MemoryResponseCache()
    service = make_service(router=router, classification_cache=cache)
    await cache.set(
        classification_cache_key(tenant_id=TENANT_A, query="What stock is low?"),
        json.dumps({"agents": ["inventory_monitor"], "confidence": 0.5}),
        ttl_seconds=300,
    )

    decision = await service.classify("What stock is low?", tenant_id=TENANT_A)

    assert decision.abstain is True
    assert decision.reason == "low_confidence"
    assert router.complete_calls == 0


async def test_corrupt_classification_entry_falls_back_to_provider() -> None:
    router = FakeLlmRouter()
    cache = MemoryResponseCache()
    service = make_service(router=router, classification_cache=cache)
    await cache.set(
        classification_cache_key(tenant_id=TENANT_A, query="What stock is low?"),
        "not-json",
        ttl_seconds=300,
    )

    decision = await service.classify("What stock is low?", tenant_id=TENANT_A)

    assert decision.agents == ("inventory_monitor",)
    assert router.complete_calls == 1


# --- response cache ---------------------------------------------------------


async def test_response_cache_skips_provider_on_repeat() -> None:
    router = FakeLlmRouter(classify_text=_ABSTAIN_ANSWER)
    service = make_service(
        router=router,
        classification_cache=MemoryResponseCache(),
        response_cache=MemoryResponseCache(),
    )

    first = await collect(service, "tell me about multi-turn accounting")
    second = await collect(service, "tell me about multi-turn accounting")

    assert tokens_text(first) == _SUPERVISOR_ANSWER
    assert tokens_text(second) == _SUPERVISOR_ANSWER
    # Turn 1: classify + supervisor answer. Turn 2: both cached.
    assert router.complete_calls == 2


async def test_response_cache_is_tenant_scoped() -> None:
    router = FakeLlmRouter(classify_text=_ABSTAIN_ANSWER)
    service = make_service(
        router=router,
        classification_cache=MemoryResponseCache(),
        response_cache=MemoryResponseCache(),
    )

    await collect(service, "tell me about accounting history")
    await collect(service, "tell me about accounting history")

    first = [
        event
        async for event in service.stream_answer(
            query="tell me about accounting history", tenant_id=TENANT_B, user_id=USER_ID
        )
    ]

    assert tokens_text(first) == _SUPERVISOR_ANSWER
    # A: 2nd turn fully cached. B: full turn again (classify + answer).
    assert router.complete_calls == 4


async def test_response_cache_expires_after_ttl() -> None:
    now = [100.0]
    router = FakeLlmRouter(classify_text=_ABSTAIN_ANSWER)
    shared_cache = MemoryResponseCache(now=lambda: now[0])
    service = make_service(
        router=router,
        classification_cache=shared_cache,
        response_cache=shared_cache,
    )

    await collect(service, "what is the meaning of life, the universe and everything")
    assert router.complete_calls == 2

    now[0] = 400.1  # past the 300s TTL on both caches
    await collect(service, "what is the meaning of life, the universe and everything")

    assert router.complete_calls == 4


async def test_response_cache_never_engages_for_images() -> None:
    router = FakeLlmRouter(classify_text=_ABSTAIN_ANSWER)
    service = make_service(router=router, response_cache=MemoryResponseCache())
    image_blocks = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]

    async def supervisor_answer() -> list[SupervisorEvent]:
        return [
            event
            async for event in service._supervisor_answer(
                query="what does this chart show?",
                image_blocks=image_blocks,
                tenant_id=TENANT_A,
            )
        ]

    first = await supervisor_answer()
    second = await supervisor_answer()

    assert tokens_text(first) == _SUPERVISOR_ANSWER
    assert tokens_text(second) == _SUPERVISOR_ANSWER
    assert router.complete_calls == 2  # both turns reach the provider


# --- conversation-history ordering (SKY-100 commit 3) -----------------------


async def test_routed_path_never_loads_conversation_history() -> None:
    """History is not on the routed-turn critical path - skip the DB read."""
    history = FakeConversationHistory()
    service = make_service(router=FakeLlmRouter(), conversation_history=history)

    events = [
        event
        async for event in service.stream_answer(
            query="What stock is below reorder point?",
            conversation_id=uuid.uuid4(),
            tenant_id=TENANT_A,
            user_id=USER_ID,
        )
    ]

    assert any(isinstance(e, ClassificationEvent) and not e.abstain for e in events)
    assert history.get_messages_calls == 0


async def test_abstain_path_loads_conversation_history() -> None:
    """The supervisor-answer path still gets multi-turn context."""
    history = FakeConversationHistory()
    router = FakeLlmRouter(classify_text=_ABSTAIN_ANSWER)
    service = make_service(router=router, conversation_history=history)

    events = [
        event
        async for event in service.stream_answer(
            query="tell me about multi-turn accounting",
            conversation_id=uuid.uuid4(),
            tenant_id=TENANT_A,
            user_id=USER_ID,
        )
    ]

    assert history.get_messages_calls == 1
    assert tokens_text(events) == _SUPERVISOR_ANSWER


async def test_abstain_history_is_bounded_to_recent_window() -> None:
    """Only the most recent 20 messages enter the prompt - never the full log.

    Guards the repo/port ``limit`` (SKY-100): a long conversation must not
    grow the supervisor prompt without bound, and the history read must not
    transfer every row from the database.
    """
    history = FakeConversationHistory(message_count=25)
    router = RecordingSupervisorRouter()
    service = make_service(router=router, conversation_history=history)

    events = [
        event
        async for event in service.stream_answer(
            query="tell me about multi-turn accounting",
            conversation_id=uuid.uuid4(),
            tenant_id=TENANT_A,
            user_id=USER_ID,
        )
    ]

    assert tokens_text(events) == _SUPERVISOR_ANSWER
    assert history.last_limit == 20
    prompt = router.last_supervisor_prompt
    assert prompt is not None
    user_lines = [line for line in prompt.splitlines() if line.startswith("User: message ")]
    assert len(user_lines) == 20
    assert any(line == "User: message 24" for line in user_lines)  # newest kept
    assert not any(line == "User: message 0" for line in user_lines)  # oldest dropped


# --- tool cache -------------------------------------------------------------


async def test_crm_nl_action_cached_per_tenant() -> None:
    gateway = FakeCrmGateway()
    delegate = make_crm_delegate(
        router=FakeLlmRouter(),
        gateway=gateway,
        tool_cache=MemoryResponseCache(),
    )
    citations = []

    async def question() -> str:
        deltas = [
            delta
            async for delta in delegate.stream(
                query="how many leads",
                tenant_id=TENANT_A,
                user_id=USER_ID,
                citations=citations,
            )
        ]
        return "".join(deltas)

    first = await question()
    second = await question()

    assert "2 leads" in first
    assert first == second
    assert gateway.list_leads_calls == 1


async def test_crm_nl_action_not_cached_without_tool_cache() -> None:
    gateway = FakeCrmGateway()
    delegate = make_crm_delegate(router=FakeLlmRouter(), gateway=gateway)

    citations = []
    async for _ in delegate.stream(
        query="how many leads",
        tenant_id=TENANT_A,
        user_id=USER_ID,
        citations=citations,
    ):
        pass
    async for _ in delegate.stream(
        query="how many leads",
        tenant_id=TENANT_A,
        user_id=USER_ID,
        citations=citations,
    ):
        pass

    assert gateway.list_leads_calls == 2


async def test_finance_deterministic_cached_per_tenant() -> None:
    gateway = FakeFinanceGateway()
    delegate = make_finance_delegate(
        router=FakeLlmRouter(),
        gateway=gateway,
        tool_cache=MemoryResponseCache(),
    )

    async def summary() -> str | None:
        return await delegate._try_deterministic("show the invoice totals", tenant_id=TENANT_A)

    first = await summary()
    second = await summary()

    assert first == second
    assert "3 invoices" in first
    assert gateway.list_invoices_calls == 1

    await delegate._try_deterministic("show the invoice totals", tenant_id=TENANT_B)

    assert gateway.list_invoices_calls == 2


async def test_finance_deterministic_uncached_by_default() -> None:
    gateway = FakeFinanceGateway()
    delegate = make_finance_delegate(router=FakeLlmRouter(), gateway=gateway)

    await delegate._try_deterministic("show the invoice totals", tenant_id=TENANT_A)
    await delegate._try_deterministic("show the invoice totals", tenant_id=TENANT_A)

    assert gateway.list_invoices_calls == 2
