"""Supervisor service - intent classification + cross-module delegation (SKY-60).

The supervisor is the Agents shell's router: one turn classifies the question
into one or more module agents, streams each segment sequentially with per-agent
attribution, and emits grounding citations. It is a STATELESS orchestration
layer - unlike the checkpointed :class:`AgentRuntime` (SKY-59) there is no
HITL pause; every segment streams and the shell renders tokens live.

Routing contract:
  * ``classify()`` → :class:`RouteDecision` - LLM intent classification (strict
    JSON) with a deterministic keyword fallback when no provider is configured
    or unavailable. Low confidence abstains (a normal explicit answer, never an
    error), mirroring the nl_query abstention pattern.
  * ``stream_answer()`` → :class:`SupervisorEvent` stream - classification,
    then per agent: ``AgentStartEvent``, ``TokenEvent``*d, ``CitationsEvent``.
    Modules that registry marks disabled stream a clean "not provisioned yet"
    abstention (SKY-60 decision #6: crm/finance start disabled).
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, Protocol

import structlog

from ai_agent.cache.response_cache import (
    ResponseCache,
    classification_cache_key,
    response_cache_key,
)
from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.core.providers import LlmRequest
from ai_agent.features.attachments.processor import ProcessedAttachments, process_attachments
from ai_agent.features.supervisor.delegates import (
    AuditGuardianDelegator,
    CoachSuggestionPort,
    CrmAssistantDelegator,
    Delegator,
    FinanceDelegator,
    ForecastPort,
    GuardianReportPort,
    HrCopilotDelegator,
    HrCopilotPort,
    InventoryMonitorDelegator,
    RagSearchPort,
    SalesCoachDelegator,
)
from ai_agent.features.supervisor.prompts import (
    ABSTENTION,
    CLASSIFY_SYSTEM_PROMPT,
    DEGRADED,
    GREETING,
    SUPERVISOR_SYSTEM_PROMPT,
    not_provisioned_message,
)
from ai_agent.features.supervisor.schemas import (
    AGENT_AUDIT_GUARDIAN,
    AGENT_CRM,
    AGENT_DISPLAY_NAMES,
    AGENT_FINANCE,
    AGENT_HR,
    AGENT_INVENTORY,
    AGENT_SALES_COACH,
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

    from ai_agent.api.v1.schemas.chat import AttachmentData
    from ai_agent.core.llm_router import LlmRouter
    from ai_agent.features.crm.gateway import CrmGatewayPort
    from ai_agent.features.crm.memory import MemoryService
    from ai_agent.features.finance.gateway import FinanceGatewayPort
    from ai_agent.features.nl_query.gateway import InventoryGatewayPort

logger = structlog.get_logger("ai_agent.supervisor")

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
        (
            "finance",
            "invoice",
            "revenue",
            "expense",
            "budget",
            "p&l",
            "cash flow",
            "costs",
            "net income",
            "net profit",
            "profit",
            "loss",
            "income",
            "margin",
            "receivable",
            "accounting",
        ),
    ),
    (
        AGENT_SALES_COACH,
        (
            "coach",
            "coaching",
            "suggestion",
            "follow up",
            "follow-up",
            "deal strategy",
            "pipeline review",
            "sales tips",
            "improve my sales",
        ),
    ),
    (
        AGENT_AUDIT_GUARDIAN,
        (
            "audit",
            "guardian",
            "flagged",
            "security finding",
            "integrity report",
            "suspicious activity",
        ),
    ),
)


class ConversationHistoryPort(Protocol):
    async def get_messages(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> list[dict[str, Any]]: ...


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
        finance_gateway_factory: Callable[[], Awaitable[FinanceGatewayPort]] | None = None,
        memory_service: MemoryService | None = None,
        forecast: ForecastPort | None = None,
        coach_suggestions: CoachSuggestionPort | None = None,
        guardian_reports: GuardianReportPort | None = None,
        conversation_history: ConversationHistoryPort | None = None,
        provisioned: Mapping[str, bool],
        confidence_threshold: float = 0.75,
        classification_cache: ResponseCache | None = None,
        response_cache: ResponseCache | None = None,
        tool_cache: ResponseCache | None = None,
        classification_cache_ttl_seconds: int = 300,
        response_cache_ttl_seconds: int = 300,
        tool_cache_ttl_seconds: int = 60,
    ) -> None:
        self._conversation_history = conversation_history
        self._llm_router = llm_router
        self._confidence_threshold = confidence_threshold
        self._provisioned = dict(provisioned)
        self._classification_cache = classification_cache
        self._response_cache = response_cache
        self._classification_cache_ttl_seconds = classification_cache_ttl_seconds
        self._response_cache_ttl_seconds = response_cache_ttl_seconds
        # Cache-hit markers feed the per-turn latency telemetry (SKY-100).
        self._classification_cache_hit = False
        self._response_cache_hit = False

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
                tool_cache=tool_cache,
                tool_cache_ttl_seconds=tool_cache_ttl_seconds,
            )
        if finance_gateway_factory is not None:
            delegates[AGENT_FINANCE] = FinanceDelegator(
                llm_router=llm_router,
                finance_gateway_factory=finance_gateway_factory,
                tool_cache=tool_cache,
                tool_cache_ttl_seconds=tool_cache_ttl_seconds,
            )
        if coach_suggestions is not None:
            delegates[AGENT_SALES_COACH] = SalesCoachDelegator(
                llm_router=llm_router,
                suggestions=coach_suggestions,
            )
        if guardian_reports is not None:
            delegates[AGENT_AUDIT_GUARDIAN] = AuditGuardianDelegator(
                llm_router=llm_router,
                guardian_reports=guardian_reports,
            )
        self._delegates = delegates

    async def classify(
        self,
        query: str,
        *,
        tenant_id: uuid.UUID | None = None,
    ) -> RouteDecision:
        """Route one question; never raises - falls back to keywords.

        The classifier LLM occasionally truncates its output (a one-token
        prefix like ``{"`` instead of full JSON). We retry once and, on a
        repeated failure, fall back to keyword routing rather than abstaining:
        a query that clearly mentions a module still reaches it even when the
        classifier LLM is flaky. Queries without any known keyword degrade to
        the supervisor answer path regardless.

        When a classification cache is wired AND ``tenant_id`` is provided,
        a repeated identical question is routed from the cache (SKY-100) -
        the first provider call of the turn is skipped on cache hit.
        """
        if self._classification_cache is not None and tenant_id is not None:
            cached = await self._classification_cache.get(
                classification_cache_key(tenant_id=tenant_id, query=query)
            )
            if cached is not None:
                self._classification_cache_hit = True
                try:
                    agents, confidence = _parse_classification(cached)
                except ValueError:
                    # Stored values are always parse-valid; treat corruption
                    # as a miss rather than routing garbage.
                    self._classification_cache_hit = False
                    return await self._classify_via_provider(query, tenant_id=tenant_id)
                return self._decision_from_parts(agents, confidence)
        self._classification_cache_hit = False
        return await self._classify_via_provider(query, tenant_id=tenant_id)

    async def _classify_via_provider(
        self,
        query: str,
        *,
        tenant_id: uuid.UUID | None,
    ) -> RouteDecision:
        if not self._llm_router.has_providers:
            return _keyword_route(query)
        for attempt in range(2):
            try:
                completion = await self._llm_router.complete(
                    LlmRequest(
                        system_prompt=CLASSIFY_SYSTEM_PROMPT,
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
                break
            except ValueError:
                logger.warning("supervisor.unparseable_classification", attempt=attempt)
        else:
            fallback = _keyword_route(query)
            if not fallback.agents:
                return RouteDecision(
                    agents=(),
                    confidence=0.0,
                    abstain=True,
                    reason="unparseable_classifier_output",
                )
            return fallback
        if self._classification_cache is not None and tenant_id is not None:
            await self._classification_cache.set(
                classification_cache_key(tenant_id=tenant_id, query=query),
                completion.text,
                ttl_seconds=self._classification_cache_ttl_seconds,
            )
        return self._decision_from_parts(agents, confidence)

    def _decision_from_parts(
        self,
        agents: tuple[str, ...],
        confidence: float,
    ) -> RouteDecision:
        """Derive the routing outcome (threshold + abstention) from parsed parts."""
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
        attachments: list[AttachmentData] | None = None,
        conversation_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AsyncIterator[SupervisorEvent]:
        """Stream one full supervisor turn as ordered events, then emit
        per-turn latency telemetry (SKY-100).

        Delegates to :meth:`_stream_turn` for the event stream; this wrapper
        times the turn (time to first ``TokenEvent`` plus total), records the
        cache-hit markers, and always logs a ``supervisor.turn_completed``
        event - even when the consumer closes the stream early.
        """
        self._classification_cache_hit = False
        self._response_cache_hit = False
        turn_started = time.perf_counter()
        first_token_ms: float | None = None
        try:
            async for event in self._stream_turn(
                query=query,
                attachments=attachments,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                user_id=user_id,
            ):
                if isinstance(event, TokenEvent) and first_token_ms is None:
                    first_token_ms = (time.perf_counter() - turn_started) * 1000
                yield event
        finally:
            total_ms = (time.perf_counter() - turn_started) * 1000
            logger.info(
                "supervisor.turn_completed",
                tenant_id=str(tenant_id),
                conversation_id=str(conversation_id) if conversation_id is not None else None,
                first_token_ms=_round_ms(first_token_ms),
                total_ms=_round_ms(total_ms),
                classification_cache_hit=self._classification_cache_hit,
                response_cache_hit=self._response_cache_hit,
                cache_hit=self._classification_cache_hit or self._response_cache_hit,
            )

    async def _stream_turn(
        self,
        *,
        query: str,
        attachments: list[AttachmentData] | None = None,
        conversation_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AsyncIterator[SupervisorEvent]:
        """Stream one full supervisor turn as ordered events.

        When attachments are present, their text content is extracted and
        appended to the query so the LLM has full context.  Images are passed
        as multimodal content blocks to the vision-capable LLM.

        When ``conversation_id`` is provided, the prior conversation history is
        loaded from the database and injected into the supervisor system prompt
        so the LLM has multi-turn context. The load happens only on the
        supervisor-answer (abstain) path - routed turns never read history, so
        it is never on the time-to-first-token critical path (SKY-100).
        """
        # --- Process attachments into LLM-ready format ---
        processed = process_attachments(attachments) if attachments else ProcessedAttachments()

        # Build the enhanced query: original question + extracted document text.
        enhanced_query = query
        if processed.extracted_text:
            enhanced_query = (
                f"{query}\n\n"
                f"--- Attached file content ---\n"
                f"{processed.extracted_text}\n"
                f"--- End of attached content ---"
            )

        # --- Classify intent (uses original query for routing, not file content) ---
        decision = await self.classify(query, tenant_id=tenant_id)
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
            if _is_greeting(query):
                # Genuine greeting - a short, friendly redirect.
                for event in _yield_text(agent="supervisor", text=GREETING):
                    yield event
            else:
                # A real question that did not route to a module: answer it as
                # the supervisor instead of deflecting with canned text, so the
                # response actually varies with what the user asked.
                #
                # History is only loaded on this abstain path (SKY-100): routed
                # turns never read it, so the DB round-trip must not sit between
                # the turn start and the classification provider call.
                conversation_history = ""
                if conversation_id is not None:
                    conversation_history = await self._load_conversation_history(
                        conversation_id=conversation_id,
                        tenant_id=tenant_id,
                    )
                async for sup_event in self._supervisor_answer(
                    query=enhanced_query,
                    image_blocks=processed.image_blocks,
                    conversation_history=conversation_history,
                    tenant_id=tenant_id,
                ):
                    yield sup_event
            yield CitationsEvent(agent="supervisor", citations=())
            yield DoneEvent(agents=("supervisor",))
            return

        handled: list[str] = []
        for agent in decision.agents:
            handled.append(agent)
            display_name = AGENT_DISPLAY_NAMES.get(agent, agent)
            yield AgentStartEvent(agent=agent, display_name=display_name)

            if not self._provisioned.get(agent, False):
                for event in _yield_text(agent=agent, text=not_provisioned_message(display_name)):
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
                    query=enhanced_query.strip(),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    citations=citations,
                ):
                    yield TokenEvent(agent=agent, delta=delta)
            except AiUnavailableError as exc:
                logger.warning("supervisor.delegate_unavailable", agent=agent, error=str(exc))
                for event in _yield_text(agent=agent, text=DEGRADED):
                    yield event
            yield CitationsEvent(agent=agent, citations=tuple(citations))

        yield DoneEvent(agents=tuple(handled))

    async def _supervisor_answer(
        self,
        *,
        query: str,
        image_blocks: list[dict[str, object]] | None = None,
        conversation_history: str = "",
        tenant_id: uuid.UUID | None = None,
    ) -> AsyncIterator[SupervisorEvent]:
        """Answer as the general supervisor, varying with the actual question.

        Used when a real request does not clearly route to a module agent. The
        supervisor answers from its own knowledge so the reply differs with the
        input, instead of returning one fixed canned string. Degrades to the
        short abstention text only when no LLM provider can be reached.

        When ``image_blocks`` are present (user attached images), the request
        is sent as a multimodal/vision call so the LLM can see the images.

        When ``conversation_history`` is provided, it is prepended to the
        system prompt so the LLM has multi-turn context.

        A response cache (SKY-100) short-circuits repeated identical questions:
        the second provider call of the turn is skipped on cache hit. Multimodal
        image requests are never cached (payloads vary and are large).
        """
        cache_key: str | None = None
        if self._response_cache is not None and tenant_id is not None and not image_blocks:
            cache_key = response_cache_key(
                tenant_id=tenant_id,
                query=query.strip(),
                conversation_history=conversation_history,
            )
            cached = await self._response_cache.get(cache_key)
            if cached:
                self._response_cache_hit = True
                for event in _yield_text(agent="supervisor", text=cached):
                    yield event
                return
        self._response_cache_hit = False
        if not self._llm_router.has_providers:
            for event in _yield_text(agent="supervisor", text=ABSTENTION):
                yield event
            return
        try:
            system_prompt = SUPERVISOR_SYSTEM_PROMPT
            if conversation_history:
                system_prompt = (
                    f"{SUPERVISOR_SYSTEM_PROMPT}\n\n"
                    f"--- Conversation history ---\n"
                    f"{conversation_history}\n"
                    f"--- End of conversation history ---"
                )
            completion = await self._llm_router.complete(
                LlmRequest(
                    system_prompt=system_prompt,
                    user_prompt=query.strip(),
                    max_tokens=512,
                    temperature=0.3,
                    image_blocks=image_blocks,
                )
            )
        except AiUnavailableError as exc:
            logger.warning("supervisor.answer_unavailable", error=str(exc))
            for event in _yield_text(agent="supervisor", text=DEGRADED):
                yield event
            return
        text = (completion.text or "").strip()
        if cache_key is not None and self._response_cache is not None and text:
            await self._response_cache.set(
                cache_key,
                text,
                ttl_seconds=self._response_cache_ttl_seconds,
            )
        for event in _yield_text(agent="supervisor", text=text or ABSTENTION):
            yield event

    async def _load_conversation_history(
        self,
        *,
        conversation_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> str:
        """Load conversation messages and format them as multi-turn context.

        Returns a formatted string of prior messages (up to the last 20) for
        injection into the supervisor system prompt. Returns empty string on
        any failure - history is best-effort and must never block the turn.
        """
        if self._conversation_history is None:
            return ""

        try:
            messages = await self._conversation_history.get_messages(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
            )
            if not messages:
                return ""

            # Take the last 20 messages to stay within token limits.
            recent = messages[-20:]
            lines: list[str] = []
            for msg in recent:
                role = "User" if msg["role"] == "user" else "Assistant"
                lines.append(f"{role}: {msg['content']}")
            return "\n".join(lines)
        except Exception:
            logger.warning(
                "supervisor.history_load_failed",
                conversation_id=str(conversation_id),
                exc_info=True,
            )
            return ""


def _round_ms(value: float | None) -> float | None:
    """Round a millisecond figure for telemetry; None stays None."""
    return round(value, 1) if value is not None else None


def _parse_classification(text: str) -> tuple[tuple[str, ...], float]:
    """Parse+Lint the classifier's JSON into (valid agent keys, confidence).

    LLMs wrap JSON in markdown fences or prose unpredictably, so when the text
    is not exactly a JSON object we hunt for the first ``{...}`` object after
    stripping fence markers and surrounding prose. Genuine garbage (no braces)
    still raises and aborts routing to the supervisor.
    """
    cleaned = text.strip()
    if "```" in cleaned:
        cleaned = "\n".join(line for line in cleaned.splitlines() if "```" not in line).strip()
    payload_text = cleaned
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        payload_text = cleaned[start : end + 1]
    try:
        payload = json.loads(payload_text)
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


_GREETING_WORDS = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "hola",
        "howdy",
        "greetings",
        "thanks",
        "thank you",
        "thank",
        "cheers",
        "bye",
        "goodbye",
        "good morning",
        "good afternoon",
        "good evening",
        "how are you",
        "how's it going",
        "what's up",
        "sup",
        "yo",
    }
)

# Words that may follow a greeting without turning it into a real question.
_GREETING_FILLERS = frozenset(
    {
        "there",
        "hello",
        "hi",
        "hey",
        "u",
        "you",
        "ya",
        "everyone",
        "guys",
        "all",
        "mate",
        "man",
    }
)


def _is_greeting(query: str) -> bool:
    """True when the message is essentially a bare greeting, not a question.

    A message is only a greeting when it holds no real content. A question such
    as "hi, what is our revenue?" is NOT a greeting, even though it starts with
    one - it is a genuine request that must be routed or answered.
    """
    normalized = " ".join(query.strip().split())
    lowered = normalized.casefold().strip("!.? \t")
    if not lowered:
        return False

    tokens = lowered.split()
    # Single greeting word, e.g. "hi", "hey", "thanks".
    if lowered in _GREETING_WORDS:
        return True
    # Short greeting plus filler, e.g. "hi there", "hello everyone".
    if len(tokens) <= 3 and tokens[0] in _GREETING_WORDS:
        rest = tokens[1:]
        if all(word in _GREETING_FILLERS for word in rest):
            return True
    return False


def _yield_text(*, agent: str, text: str) -> Iterator[TokenEvent]:
    for delta in _iter_text_deltas(text):
        yield TokenEvent(agent=agent, delta=delta)


def _iter_text_deltas(text: str) -> Iterator[str]:
    """Split buffered text into word-slices joined with spaces (streaming shape)."""
    words = text.split(" ")
    for index, word in enumerate(words):
        yield word + (" " if index < len(words) - 1 else "")
