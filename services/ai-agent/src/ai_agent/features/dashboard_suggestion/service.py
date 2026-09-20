"""Dashboard layout suggestion service - LLM-backed recommendations from telemetry.

The honest-status contract (BUG-AI-002): a suggestion request ALWAYS returns
an explicit ``status`` marker, never a silent empty 200. Three outcomes:

- ``suggested``         - Core reported enough telemetry and the LLM produced
                          a valid layout; confidence reflects a real signal.
- ``insufficient_data`` - Core's own threshold (``suggestion_ready``) is not
                          met. The current layout is returned untouched and
                          NO LLM call is made - no fabrication, no API spend.
- ``fallback``          - no LLM provider configured, the LLM call failed, or
                          the response was unparseable. Current layout kept.

The telemetry ALWAYS comes from Core through the gateway (never invented
here), and the prompt only ever names widgets already present in the current
layout - the LLM cannot hallucinate widgets into the suggestion.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from ai_agent.core.llm_router import LlmRouter
from ai_agent.core.providers.base import LlmRequest
from ai_agent.features.dashboard_suggestion.gateway import (
    DashboardGatewayPort,
    EventSummary,
)

logger = structlog.get_logger("ai_agent.dashboard_suggestion")

SUGGESTION_SYSTEM_PROMPT = """\
You are a dashboard layout advisor for an ERP system.  You analyze widget \
interaction telemetry and suggest layout improvements.

Rules:
- Return a JSON object: {"layout": [...], "reasoning": "..."}
- Widgets with high open counts should appear earlier (lower order) and wider
  (cols 1-4); widgets with zero or very few events should be hidden or moved
  to the end.
- Do NOT add, rename, or drop widgets that are not in the current layout.
- Respond with ONLY one JSON object, never prose."""


class DashboardSuggestionService:
    """Orchestrates AI-powered layout suggestions from Core telemetry."""

    def __init__(self, llm_router: LlmRouter, gateway: DashboardGatewayPort) -> None:
        self._llm_router = llm_router
        self._gateway = gateway

    async def suggest(
        self,
        *,
        tenant_id: uuid.UUID,
        current_layout: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate a layout suggestion based on Core's telemetry.

        Args:
            tenant_id: Caller's tenant (for the gateway fetch).
            current_layout: The user's current layout items.

        Returns:
            Dict with status, suggested_layout, reasoning, and confidence.
        """
        summary = await self._gateway.get_event_summary()

        if not summary.suggestion_ready:
            return {
                "status": "insufficient_data",
                "suggested_layout": current_layout,
                "reasoning": (
                    "Not enough widget telemetry yet - keep the current layout "
                    "and interact with your dashboard. Suggestion unlocks "
                    "after more usage data is collected."
                ),
                "confidence": 0.0,
            }

        if not self._llm_router.has_providers:
            return self._fallback(current_layout)

        user_prompt = self._build_prompt(current_layout, summary)

        try:
            completion = await self._llm_router.complete(
                LlmRequest(
                    system_prompt=SUGGESTION_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    max_tokens=512,
                    temperature=0.3,
                    json_mode=True,
                )
            )
        except Exception as exc:
            logger.warning("dashboard_suggestion.llm_failed", error=str(exc))
            return self._fallback(current_layout)

        return self._parse_response(completion.text or "", current_layout)

    def _build_prompt(
        self,
        current_layout: list[dict[str, Any]],
        summary: EventSummary,
    ) -> str:
        """Build the user prompt with layout + telemetry context."""
        layout_str = json.dumps(current_layout, indent=2)
        events_str = "\n".join(
            f"- {item.widget_id}: {item.total_events} events "
            f"({item.distinct_events} distinct)"
            for item in summary.items
        ) or "No widget telemetry recorded yet."

        return f"Current layout:\n{layout_str}\n\nWidget interaction events:\n{events_str}"

    def _parse_response(self, text: str, current_layout: list[dict[str, Any]]) -> dict[str, Any]:
        """Parse the LLM response into a structured suggestion."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            ).strip()

        try:
            payload = json.loads(cleaned)
        except ValueError:
            logger.warning("dashboard_suggestion.parse_failed")
            return self._fallback(current_layout)

        raw_layout = payload.get("layout", [])
        reasoning = payload.get("reasoning", "No reasoning provided.")

        valid_ids = {item["id"] for item in current_layout}
        validated: list[dict[str, Any]] = []
        for i, item in enumerate(raw_layout):
            if not isinstance(item, dict) or item.get("id") not in valid_ids:
                continue
            validated.append(
                {
                    "id": item["id"],
                    "order": item.get("order", i),
                    "cols": max(1, min(4, item.get("cols", 4))),
                    "visible": item.get("visible", True),
                }
            )

        if not validated:
            return self._fallback(current_layout)

        return {
            "status": "suggested",
            "suggested_layout": validated,
            "reasoning": reasoning,
            "confidence": 0.7,
        }

    def _fallback(self, current_layout: list[dict[str, Any]]) -> dict[str, Any]:
        """Return the current layout as-is with an honest fallback marker."""
        return {
            "status": "fallback",
            "suggested_layout": current_layout,
            "reasoning": "AI suggestion unavailable - showing current layout.",
            "confidence": 0.0,
        }
