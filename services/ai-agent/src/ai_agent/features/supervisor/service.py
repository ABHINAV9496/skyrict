"""Supervisor service — intent classification + cross-module delegation (SKY-60).

The supervisor is the Agents shell's router: one turn classifies the question
into one or more module agents, streams each segment sequentially with per-agent
attribution, and emits grounding citations. It is a STATELESS orchestration
layer — unlike the checkpointed :class:`AgentRuntime` (SKY-59) there is no
HITL pause; every segment streams and the shell renders tokens live.

Routing contract:
  * ``classify()`` → :class:`RouteDecision` — LLM intent classification (strict
    JSON) with a deterministic keyword fallback when no provider is configured
    or unavailable. Low confidence abstains (a normal explicit answer, never an
    error), mirroring the nl_query abstention pattern.
  * ``stream_answer()`` → :class:`SupervisorEvent` stream — classification,
    then per agent: ``AgentStartEvent``, ``TokenEvent``*d, ``CitationsEvent``.
    Modules that registry marks disabled stream a clean "not provisioned yet"
    abstention (SKY-60 decision #6: crm/finance start disabled).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog

from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.core.providers import LlmRequest
from ai_agent.features.supervisor.delegates import (
    CrmAssistantDelegator,
    Delegator,
    ForecastPort,
    HrCopilotDelegator,
    HrCopilotPort,
    InventoryMonitorDelegator,
    RagSearchPort,
)
from ai_agent.features.supervisor.schemas import (
    AGENT_CRM,
    AGENT_DISPLAY_NAMES,
    AGENT_FINANCE,
    AGENT_HR,
    AGENT_INVENTORY,
    AgentStartEvent,
    Citation,
    CitationsEvent,
    ClassificationEvent,
    DoneEvent,
    RouteDecision,
    SupervisorEvent,
    TokenEvent,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping

    from ai_agent.core.llm_router import LlmRouter
    from ai_agent.features.crm.gateway import CrmGatewayPort
    from ai_agent.features.crm.memory import MemoryService
    from ai_agent.features.nl_query.gateway import InventoryGatewayPort

logger = structlog.get_logger("ai_agent.supervisor")

_ABSTENTION = (
    "I'm not sure I understood the question well enough to route it to a module "
    "agent. Try rephrasing it — for example 'What stock is below reorder "
    "point?' or 'Summarize our leave policy'."
)

_DEGRADED = "That agent hit a temporary snag — please try again shortly."

_CLASSIFY_SYSTEM_PROMPT = (
    "You are the routing classifier for the Skyrict agents shell. Decide which "
    "module agent(s) should answer the user's question. Respond with ONE JSON "
    'object, no prose: {"agents": ["<agent>", ...], "confidence": 0.0-1.0}\n'
    'Allowed agents: "inventory_monitor" (stock, movements, reorder, '
    'forecasts), "hr_copilot" (leave, policies, employee questions), '
    '"crm_assistant" (customers, leads, opportunities), "finance_assistant" '
    "(invoices, revenue, expenses, budget). Use MULTIPLE agents for a "
    "question that spans modules, primary agent first. Set confidence low "
    "when the mapping is unclear."
)

_KEYWORD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        AGENT_INVENTORY,
        (
            "stock",
            "inventory",
            "reorder",
            "movement",
            "sku",
            "warehouse",
            "receipt",
            "reserved",
            "on hand",
            "forecast",
            "demand",
        ),
    ),
    (
        AGENT_HR,
        (
            "hr",
            "leave",
            "policy",
            "employee",
            "onboarding",
            "payroll",
            "benefit",
            "appraisal",
            "attrition",
            "headcount",
        ),
    ),
    (AGENT_CRM, ("crm", "customer", "lead", "opportunity", "pipeline", "sales")),
    (
        AGENT_FINANCE,
        ("finance", "invoice", "revenue", "expense", "budget", "p&l", "cash flow", "costs"),
    ),
)


class SupervisorService:
    """Routes one Agents-shell question and streams the delegated answer."""

    def __init__(
        self,
        *,
        llm_router: LlmRouter,
        gateway_factory: Callable[[], Awaitable[InventoryGatewayPort]],
        rag: RagSearchPort | None = None,
        hr_copilot: HrCopilotPort | None = None,
        crm_gateway_factory: Callable[[], Awaitable[CrmGatewayPort]] | None = None,
        memory_service: MemoryService | None = None,
        forecast: ForecastPort | None = None,
        provisioned: Mapping[str, bool],
        confidence_threshold: float = 0.75,
    ) -> None:
        self._llm_router = llm_router
        self._confidence_threshold = confidence_threshold
        self._provisioned = dict(provisioned)

        delegates: dict[str, Delegator] = {
            AGENT_INVENTORY: InventoryMonitorDelegator(
                llm_router=llm_router,
                gateway_factory=gateway_factory,
                rag=rag,
                forecast=forecast,
            )
        }
        if hr_copilot is not None:
            delegates[AGENT_HR] = HrCopilotDelegator(hr_copilot=hr_copilot)
        if crm_gateway_factory is not None:
            delegates[AGENT_CRM] = CrmAssistantDelegator(
                llm_router=llm_router,
                crm_gateway_factory=crm_gateway_factory,
                memory_service=memory_service,
            )
        self._delegates = delegates

    async def classify(self, query: str) -> RouteDecision:
        """Route one question; never raises — falls back to keywords."""
        if not self._llm_router.has_providers:
            return _keyword_route(query)
        try:
            completion = await self._llm_router.complete(
                LlmRequest(
                    system_prompt=_CLASSIFY_SYSTEM_PROMPT,
                    user_prompt=query.strip(),
                    max_tokens=128,
                    temperature=0.0,
                )
            )
        except AiUnavailableError as exc:
            logger.warning("supervisor.classifier_unavailable", error=str(exc))
            return _keyword_route(query)

        try:
            agents, confidence = _parse_classification(completion.text)
        except ValueError:
            logger.warning("supervisor.unparseable_classification")
            return RouteDecision(
                agents=(), confidence=0.0, abstain=True, reason="unparseable_classifier_output"
            )
        if not agents:
            return RouteDecision(agents=(), confidence=confidence, abstain=True, reason="no_agents")
        if confidence < self._confidence_threshold:
            return RouteDecision(
                agents=agents, confidence=confidence, abstain=True, reason="low_confidence"
            )
        return RouteDecision(agents=agents, confidence=confidence, abstain=False, reason="routed")

    async def stream_answer(
        self,
        *,
        query: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AsyncIterator[SupervisorEvent]:
        """Stream one full supervisor turn as ordered events."""
        decision = await self.classify(query)
        yield ClassificationEvent(
            agents=decision.agents,
            confidence=decision.confidence,
            abstain=decision.abstain,
            reason=decision.reason,
        )

        if decision.abstain or not decision.agents:
            yield AgentStartEvent(
                agent="supervisor", display_name=AGENT_DISPLAY_NAMES["supervisor"]
            )
            for event in _yield_text(agent="supervisor", text=_ABSTENTION):
                yield event
            yield CitationsEvent(agent="supervisor", citations=())
            yield DoneEvent(agents=("supervisor",))
            return

        handled: list[str] = []
        for agent in decision.agents:
            handled.append(agent)
            display_name = AGENT_DISPLAY_NAMES.get(agent, agent)
            yield AgentStartEvent(agent=agent, display_name=display_name)

            if not self._provisioned.get(agent, False):
                for event in _yield_text(agent=agent, text=_not_provisioned_message(display_name)):
                    yield event
                yield CitationsEvent(agent=agent, citations=())
                continue

            delegator = self._delegates.get(agent)
            if delegator is None:
                for event in _yield_text(
                    agent=agent, text=f"The {display_name} module has no live delegate yet."
                ):
                    yield event
                yield CitationsEvent(agent=agent, citations=())
                continue

            citations: list[Citation] = []
            try:
                async for delta in delegator.stream(
                    query=query.strip(),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    citations=citations,
                ):
                    yield TokenEvent(agent=agent, delta=delta)
            except AiUnavailableError as exc:
                logger.warning("supervisor.delegate_unavailable", agent=agent, error=str(exc))
                for event in _yield_text(agent=agent, text=_DEGRADED):
                    yield event
            yield CitationsEvent(agent=agent, citations=tuple(citations))

        yield DoneEvent(agents=tuple(handled))


def _parse_classification(text: str) -> tuple[tuple[str, ...], float]:
    """Parse+Lint the classifier's JSON into (valid agent keys, confidence)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(
            line for line in cleaned.splitlines() if not line.strip().startswith("```")
        ).strip()
    try:
        payload = json.loads(cleaned)
    except ValueError as exc:
        raise ValueError("classifier output is not JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("classifier output is not an object")

    raw_agents = payload.get("agents")
    if not isinstance(raw_agents, list) or not raw_agents:
        return (), 0.0
    agents: list[str] = []
    for raw in raw_agents:
        if isinstance(raw, str) and raw in AGENT_DISPLAY_NAMES and raw not in agents:
            agents.append(raw)

    raw_confidence = payload.get("confidence")
    if isinstance(raw_confidence, (int, float)):
        confidence = max(0.0, min(1.0, float(raw_confidence)))
    else:
        confidence = 0.0
    return tuple(agents), confidence


def _keyword_route(query: str) -> RouteDecision:
    """Deterministic fallback used when no LLM provider is available."""
    lowered = query.casefold()
    matched = [key for key, keywords in _KEYWORD_RULES if any(w in lowered for w in keywords)]
    if not matched:
        return RouteDecision(
            agents=(), confidence=0.0, abstain=True, reason="no_provider_no_keywords"
        )
    return RouteDecision(
        agents=tuple(matched), confidence=0.65, abstain=False, reason="keyword_fallback"
    )


def _yield_text(*, agent: str, text: str) -> Iterator[TokenEvent]:
    for delta in _iter_text_deltas(text):
        yield TokenEvent(agent=agent, delta=delta)


def _iter_text_deltas(text: str) -> Iterator[str]:
    """Split buffered text into word-slices joined with spaces (streaming shape)."""
    words = text.split(" ")
    for index, word in enumerate(words):
        yield word + (" " if index < len(words) - 1 else "")


def _not_provisioned_message(display_name: str) -> str:
    return (
        f"The {display_name} module is not provisioned for this workspace yet — "
        "your question has been noted. Ask the supervisor again once it's enabled."
    )
