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
from typing import TYPE_CHECKING, Protocol

import structlog

from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.core.providers import LlmRequest
from ai_agent.features.supervisor.schemas import AGENT_HR, AGENT_INVENTORY, Citation

if TYPE_CHECKING:
    import uuid
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

    from ai_agent.core.llm_router import LlmRouter
    from ai_agent.features.hr_copilot.engine import HrCopilotResult
    from ai_agent.features.nl_query.gateway import InventoryGatewayPort
    from ai_agent.features.rag.retrieval.service import RetrievalResult

logger = structlog.get_logger("ai_agent.supervisor.delegates")

_INVENTORY_SYSTEM_PROMPT = (
    "You are the Inventory Monitor agent for Skyrict. Answer concisely using "
    "the provided reference context: live stock counts from the ERP and any "
    "knowledge-base excerpts. If the context does not answer the question, "
    "say what data you would need. Lead with the most relevant number."
)

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
            system_prompt=_INVENTORY_SYSTEM_PROMPT,
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
        """Provider-free answer — live facts only, no LLM (dev/demo path)."""
        if context_parts:
            return "Here is what Inventory Monitor finds right now: " + " ".join(context_parts[:4])
        return (
            "Inventory Monitor: I couldn't reach live inventory data right now — "
            "try again in a moment."
        )


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
            for delta in _iter_text_deltas(
                "The HR Copilot is temporarily unavailable — please try again shortly."
            ):
                yield delta
            return
        answer = (result.answer or "").strip()
        if answer:
            for delta in _iter_text_deltas(answer):
                yield delta
        else:
            for delta in _iter_text_deltas(
                "I couldn't find an answer to that in the HR knowledge base yet."
            ):
                yield delta


def _iter_text_deltas(text: str) -> Iterator[str]:
    """Split buffered answer text into word-slices joined with spaces."""
    words = text.split(" ")
    for index, word in enumerate(words):
        yield word + (" " if index < len(words) - 1 else "")
