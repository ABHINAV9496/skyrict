"""Leaf module adapters — each streams token deltas for one registered agent.

Contract: a delegator is an async generator over ``str`` token deltas. The
``citations`` list is an out-param — the orchestrator reads it AFTER the
segment completes to emit the citations event, keeping the token stream free
of control frames.

Security notes:
  * Inventory data is READ-ONLY via the nl_query gateway (the core proxy edge);
    only counts and names enter prompts — never ``cost_price`` (spec §5.5
    local-only money data).
  * RAG retrieval and forecast reads are best-effort: a failure degrades the
    answer, it never kills the stream — the shell always receives tokens.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar, Protocol

import structlog

from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.core.providers import LlmRequest
from ai_agent.features.supervisor.prompts import (
    CRM_NO_ANSWER,
    CRM_SYSTEM_PROMPT,
    CRM_UNAVAILABLE,
    HR_NO_ANSWER,
    HR_UNAVAILABLE,
    INVENTORY_NO_DATA,
    INVENTORY_SYSTEM_PROMPT,
)
from ai_agent.features.supervisor.schemas import AGENT_CRM, AGENT_HR, AGENT_INVENTORY, Citation

if TYPE_CHECKING:
    import uuid
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

    from ai_agent.core.llm_router import LlmRouter
    from ai_agent.features.crm.gateway import CrmGatewayPort
    from ai_agent.features.crm.memory import MemoryService
    from ai_agent.features.hr_copilot.engine import HrCopilotResult
    from ai_agent.features.nl_query.gateway import InventoryGatewayPort
    from ai_agent.features.rag.retrieval.service import RetrievalResult

logger = structlog.get_logger("ai_agent.supervisor.delegates")

# Catalogue reads are capped the same way the nl_query gateway caps them.
_FORECAST_CATALOG_LIMIT = 200
_FORECAST_ROWS_SHOWN = 3


class RagSearchPort(Protocol):
    """Semantic retrieval over the tenant's documents (rag retrieval service)."""

    async def search(
        self,
        *,
        query: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        module: str | None = None,
    ) -> RetrievalResult: ...


class ForecastPort(Protocol):
    """Moving-average demand forecast for one product (forecast service)."""

    async def get_forecast(self, *, product_id: uuid.UUID) -> list[dict[str, object]]: ...


class HrCopilotPort(Protocol):
    """The grounded HR Copilot pipeline (limit + audit live in its service)."""

    async def ask(
        self,
        *,
        message: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> HrCopilotResult: ...


class Delegator(Protocol):
    """A registered module agent that streams answer tokens."""

    key: str
    display_name: str

    def stream(
        self,
        *,
        query: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        citations: list[Citation],
    ) -> AsyncIterator[str]: ...


class InventoryMonitorDelegator:
    """Stock/forecast/RAG answers over the nl_query gateway + forecast + RAG."""

    key = AGENT_INVENTORY
    display_name = "Inventory Monitor"

    _FORECAST_HINT_WORDS = (
        "forecast",
        "demand",
        "project",
        "stock out",
        "replenish",
        "next month",
    )
    _MAX_CONTEXT_CHARS = 4000

    def __init__(
        self,
        *,
        llm_router: LlmRouter,
        gateway_factory: Callable[[], Awaitable[InventoryGatewayPort]],
        rag: RagSearchPort | None = None,
        forecast: ForecastPort | None = None,
    ) -> None:
        self._llm_router = llm_router
        self._gateway_factory = gateway_factory
        self._rag = rag
        self._forecast = forecast

    async def stream(
        self,
        *,
        query: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        citations: list[Citation],
    ) -> AsyncIterator[str]:
        context_parts = await self._gather_context(
            query=query, tenant_id=tenant_id, user_id=user_id, citations=citations
        )
        if not self._llm_router.has_providers:
            for delta in _iter_text_deltas(self._deterministic_summary(context_parts)):
                yield delta
            return

        context_text = "\n".join(context_parts)
        if len(context_text) > self._MAX_CONTEXT_CHARS:
            context_text = context_text[: self._MAX_CONTEXT_CHARS] + "…"
        request = LlmRequest(
            system_prompt=INVENTORY_SYSTEM_PROMPT,
            user_prompt=(
                "User question: "
                + query.strip()
                + "\n\nReference context:\n"
                + (context_text or "(no context available yet)")
            ),
            max_tokens=512,
            temperature=0.2,
        )
        async for chunk in self._llm_router.stream(request):
            yield chunk.token_delta

    async def _gather_context(
        self,
        *,
        query: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        citations: list[Citation],
    ) -> list[str]:
        """RAG top-k + live stock totals + optional product forecast.

        Every read is best-effort and bounded; failures degrade the prompt,
        they never raise (the shell still gets an answer).
        """
        parts: list[str] = []
        lowered = query.casefold()

        if self._rag is not None:
            try:
                result = await self._rag.search(
                    query=query,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    module="inventory",
                )
            except Exception as exc:  # retrieval must never kill the stream
                logger.warning("supervisor.rag_failed", error=str(exc))
                result = None
            if result is not None:
                for item in result.data[:3]:
                    parts.append(f"[{item.source_ref}] {item.chunk_text}")
                    citations.append(Citation(source_ref=item.source_ref, module=item.module))

        try:
            gateway = await self._gateway_factory()
            levels = await gateway.get_stock_levels()
        except AiUnavailableError as exc:
            logger.warning("supervisor.inventory_gateway_failed", error=str(exc))
            levels = []
        if levels:
            on_hand = sum((row.qty_on_hand for row in levels), Decimal(0))
            reserved = sum((row.qty_reserved for row in levels), Decimal(0))
            warehouse_ids = {str(row.warehouse_id) for row in levels}
            parts.append(
                f"Live stock: {on_hand} units on hand, {reserved} reserved "
                f"across {len(warehouse_ids)} warehouse(s)."
            )

        if self._forecast is not None and any(
            word in lowered for word in self._FORECAST_HINT_WORDS
        ):
            try:
                gateway = await self._gateway_factory()
                products = await gateway.list_products()
            except AiUnavailableError as exc:
                logger.warning("supervisor.forecast_catalog_failed", error=str(exc))
                products = []
            for product in products[:_FORECAST_CATALOG_LIMIT]:
                if product.name.casefold() not in lowered and product.sku.casefold() not in lowered:
                    continue
                try:
                    rows = await self._forecast.get_forecast(product_id=product.id)
                except Exception as exc:  # one product's forecast failure is best-effort
                    logger.warning(
                        "supervisor.forecast_failed",
                        error=str(exc),
                        product_id=str(product.id),
                    )
                    continue
                parts.append(
                    f"Forecast for {product.name} ({product.sku}): {rows[:_FORECAST_ROWS_SHOWN]}"
                )
        return parts

    def _deterministic_summary(self, context_parts: list[str]) -> str:
        """Provider-free answer - live facts only, no LLM (dev/demo path)."""
        if context_parts:
            return "Here is what Inventory Monitor finds right now: " + " ".join(context_parts[:4])
        return INVENTORY_NO_DATA


class HrCopilotDelegator:
    """HR answers through the existing grounded HR Copilot service."""

    key = AGENT_HR
    display_name = "HR Copilot"

    def __init__(self, *, hr_copilot: HrCopilotPort) -> None:
        self._hr_copilot = hr_copilot

    async def stream(
        self,
        *,
        query: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        citations: list[Citation],
    ) -> AsyncIterator[str]:
        try:
            result = await self._hr_copilot.ask(message=query, tenant_id=tenant_id, user_id=user_id)
        except AiUnavailableError as exc:
            logger.warning("supervisor.hr_copilot_failed", error=str(exc))
            for delta in _iter_text_deltas(HR_UNAVAILABLE):
                yield delta
            return
        answer = (result.answer or "").strip()
        if answer:
            for delta in _iter_text_deltas(answer):
                yield delta
        else:
            for delta in _iter_text_deltas(HR_NO_ANSWER):
                yield delta


class CrmAssistantDelegator:
    """CRM answers through deterministic NL actions + LLM fallback."""

    key = AGENT_CRM
    display_name = "CRM Assistant"

    _ACTION_KEYWORDS: ClassVar[dict[str, tuple[str, str | None]]] = {
        "count": ("count_deals", None),
        "how many deals": ("count_deals", None),
        "how many opportunities": ("count_deals", None),
        "how many leads": ("count_leads", None),
        "pipeline by stage": ("value_by_stage", None),
        "value by stage": ("value_by_stage", None),
        "deal value": ("value_by_stage", None),
        "at risk": ("at_risk", None),
        "stale": ("at_risk", None),
        "no activity": ("no_activity", None),
        "inactive": ("no_activity", None),
        "hasn't been contacted": ("no_activity", "lead"),
        "hasnt been contacted": ("no_activity", "lead"),
        "report": ("pipeline_summary", None),
        "summary": ("pipeline_summary", None),
        "overview": ("pipeline_summary", None),
        "pipeline": ("pipeline_summary", None),
    }

    def __init__(
        self,
        *,
        llm_router: LlmRouter,
        crm_gateway_factory: Callable[[], Awaitable[CrmGatewayPort]],
        memory_service: MemoryService | None = None,
    ) -> None:
        self._llm_router = llm_router
        self._crm_gateway_factory = crm_gateway_factory
        self._memory = memory_service

    async def stream(
        self,
        *,
        query: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        citations: list[Citation],
    ) -> AsyncIterator[str]:
        # Try deterministic NL actions first.
        action_result = await self._try_nl_action(query)
        if action_result is not None:
            for delta in _iter_text_deltas(action_result):
                yield delta
            return

        # Fallback: LLM with live CRM context + memory.
        try:
            system_prompt = CRM_SYSTEM_PROMPT

            # Gather live CRM data from the database so the LLM can see it.
            crm_context = await self._gather_crm_context(query)
            if crm_context:
                system_prompt = f"{system_prompt}\n\nLive CRM data:\n{crm_context}"

            # Inject relevant memories into context.
            if self._memory is not None:
                memory_ctx = await self._memory.recall_context(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    query=query,
                )
                if memory_ctx:
                    system_prompt = f"{system_prompt}\n\n{memory_ctx}"

            completion = await self._llm_router.complete(
                LlmRequest(
                    system_prompt=system_prompt,
                    user_prompt=query.strip(),
                    max_tokens=512,
                    temperature=0.0,
                )
            )
            answer = (completion.text or "").strip()
            if answer:
                for delta in _iter_text_deltas(answer):
                    yield delta
                # Store conversation in memory (fire-and-forget).
                if self._memory is not None:
                    await self._memory.store_after_chat(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        query=query,
                        response=answer,
                        module="crm_assistant",
                    )
            else:
                for delta in _iter_text_deltas(CRM_NO_ANSWER):
                    yield delta
        except AiUnavailableError as exc:
            logger.warning("supervisor.crm_assistant_failed", error=str(exc))
            for delta in _iter_text_deltas(CRM_UNAVAILABLE):
                yield delta

    async def _gather_crm_context(self, query: str) -> str:
        """Fetch live CRM data from the gateway and format it as LLM context.

        Always includes lead and opportunity summaries. For specific entity
        queries, also fetches the relevant records. Capped to avoid
        overwhelming the LLM with too much data.
        """
        try:
            gateway = await self._crm_gateway_factory()
        except AiUnavailableError:
            return ""

        parts: list[str] = []
        lowered = query.casefold()

        # Always include opportunity summary
        try:
            opportunities = await gateway.list_opportunities()
            if opportunities:
                stage_counts: dict[str, int] = {}
                for opp in opportunities:
                    stage_counts[opp.stage] = stage_counts.get(opp.stage, 0) + 1
                parts.append(f"Total opportunities: {len(opportunities)}")
                for stage, count in sorted(stage_counts.items()):
                    parts.append(f"  - {stage}: {count}")
            else:
                parts.append("No opportunities in the pipeline yet.")
        except AiUnavailableError:
            pass

        # Always include lead summary
        try:
            leads = await gateway.list_leads()
            if leads:
                status_counts: dict[str, int] = {}
                for lead in leads:
                    status_counts[lead.status] = status_counts.get(lead.status, 0) + 1
                parts.append(f"\nTotal leads: {len(leads)}")
                for status, count in sorted(status_counts.items()):
                    parts.append(f"  - {status}: {count}")
            else:
                parts.append("\nNo leads in the system yet.")
        except AiUnavailableError:
            pass

        # For opportunity-specific queries, include deal names
        if any(w in lowered for w in ("deal", "opportunity", "pipeline", "stage")):
            try:
                opportunities = await gateway.list_opportunities()
                if opportunities:
                    details = []
                    for opp in opportunities[:20]:  # Cap at 20
                        name = opp.display_name or str(opp.id)
                        details.append(
                            f"  - {name}: stage={opp.stage}, probability={opp.probability}%"
                        )
                    if details:
                        parts.append("\nDeal details:")
                        parts.extend(details)
            except AiUnavailableError:
                pass

        # For lead-specific queries, include lead names
        if any(w in lowered for w in ("lead", "prospect", "contact")):
            try:
                leads = await gateway.list_leads()
                if leads:
                    details = []
                    for lead in leads[:20]:  # Cap at 20
                        name = lead.display_name or str(lead.id)
                        details.append(
                            f"  - {name}: status={lead.status}, source={lead.source or 'unknown'}"
                        )
                    if details:
                        parts.append("\nLead details:")
                        parts.extend(details)
            except AiUnavailableError:
                pass

        return "\n".join(parts)

    async def _try_nl_action(self, query: str) -> str | None:
        """Match query keywords to a deterministic CRM NL action."""
        lower = query.lower()
        for keyword, (action, entity_type) in self._ACTION_KEYWORDS.items():
            if keyword in lower:
                return await self._execute_nl_action(action, entity_type, lower)
        return None

    async def _execute_nl_action(self, action: str, entity_type: str | None, query: str) -> str:
        from ai_agent.features.crm import nl_actions

        gateway = await self._crm_gateway_factory()
        if action == "count_deals":
            stage = self._extract_stage(query)
            result = await nl_actions.count_deals(gateway=gateway, stage=stage)
        elif action == "count_leads":
            result = await nl_actions.count_leads(gateway=gateway)
        elif action == "value_by_stage":
            result = await nl_actions.value_by_stage(gateway=gateway)
        elif action == "pipeline_summary":
            result = await nl_actions.pipeline_summary(gateway=gateway)
        elif action == "at_risk":
            result = await nl_actions.at_risk(gateway=gateway)
        elif action == "no_activity":
            result = await nl_actions.no_activity(
                gateway=gateway,
                entity_type=entity_type,
            )
        else:
            return "This CRM action is not yet implemented."
        return result.answer

    @staticmethod
    def _extract_stage(query: str) -> str | None:
        """Best-effort stage extraction from the query."""
        stage_keywords = (
            "lead",
            "qualified",
            "proposal",
            "negotiation",
            "closed won",
            "closed lost",
            "discovery",
        )
        for stage in stage_keywords:
            if stage in query:
                return stage
        return None


def _iter_text_deltas(text: str) -> Iterator[str]:
    """Split buffered answer text into word-slices joined with spaces."""
    words = text.split(" ")
    for index, word in enumerate(words):
        yield word + (" " if index < len(words) - 1 else "")
