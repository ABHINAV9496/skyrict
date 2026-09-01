"""Dashboard layout suggestion service.

Uses widget interaction telemetry to suggest layout improvements.
The LLM analyzes open/hide event patterns and recommends reordering,
resizing, or hiding widgets that the user rarely interacts with.
"""

from __future__ import annotations

import json

import structlog

from ai_agent.core.providers import LlmRequest

logger = structlog.get_logger("ai_agent.dashboard_suggestion")

SUGGESTION_SYSTEM_PROMPT = """\
You are a dashboard layout advisor for an ERP system.  You analyze widget \
interaction telemetry and suggest layout improvements.

You have access to:
- The user's current dashboard layout (widget IDs, order, column spans, visibility)
- Per-widget interaction event counts (open/hide events)

Your task is to suggest a better layout that surfaces the widgets the user \
actually uses and hides or deprioritizes ones they ignore.

Rules:
- Return a JSON array of widget layout items: [{"id": "...", "order": N, "cols": N, "visible": true/false}]
- Widgets with high open counts should appear earlier (lower order) and wider (more cols)
- Widgets with zero or very few events should be hidden (visible: false) or moved to the end
- Do NOT add widgets that aren't in the current layout
- Do NOT change widget IDs
- Keep total visible widgets reasonable (3-6 is ideal)
- Explain your reasoning in 1-2 sentences

Available widgets:
- ai_digest: Intelligence digest (daily AI summary)
- erp_overview: At a glance (pipeline + orders)
- module_quick_links: Module navigation cards
- reports_kpis: Report KPIs (finance data)

Respond with ONLY a JSON object: {"layout": [...], "reasoning": "..."}"""


class DashboardSuggestionService:
    """Orchestrates AI-powered layout suggestions from telemetry data."""

    def __init__(self, llm_router: object) -> None:
        self._llm_router = llm_router

    async def suggest(
        self,
        *,
        current_layout: list[dict],
        event_summary: list[dict],
    ) -> dict:
        """Generate a layout suggestion based on telemetry.

        Args:
            current_layout: The user's current layout items.
            event_summary: Per-widget event counts from core.

        Returns:
            Dict with suggested_layout, reasoning, and confidence.
        """
        if not self._llm_router.has_providers:  # type: ignore[attr-defined]
            return self._fallback_suggestion(current_layout)

        # Build the user prompt with layout + telemetry context
        user_prompt = self._build_prompt(current_layout, event_summary)

        try:
            completion = await self._llm_router.complete(  # type: ignore[attr-defined]
                LlmRequest(
                    system_prompt=SUGGESTION_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    max_tokens=512,
                    temperature=0.3,
                )
            )
        except Exception as exc:
            logger.warning("dashboard_suggestion.llm_failed", error=str(exc))
            return self._fallback_suggestion(current_layout)

        return self._parse_response(completion.text or "", current_layout)

    def _build_prompt(self, current_layout: list[dict], event_summary: list[dict]) -> str:
        """Build the user prompt with layout and telemetry data."""
        layout_str = json.dumps(current_layout, indent=2)
        events_str = (
            json.dumps(event_summary, indent=2) if event_summary else "No telemetry data yet."
        )

        return (
            f"Current layout:\n{layout_str}\n\n"
            f"Widget interaction events:\n{events_str}\n\n"
            "Suggest an improved layout based on this data."
        )

    def _parse_response(self, text: str, current_layout: list[dict]) -> dict:
        """Parse the LLM response into a structured suggestion."""
        cleaned = text.strip()
        # Strip markdown fences if present
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            ).strip()

        try:
            payload = json.loads(cleaned)
        except ValueError:
            logger.warning("dashboard_suggestion.parse_failed")
            return self._fallback_suggestion(current_layout)

        raw_layout = payload.get("layout", [])
        reasoning = payload.get("reasoning", "No reasoning provided.")

        # Validate layout items against current layout
        valid_ids = {item["id"] for item in current_layout}
        validated = []
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
            return self._fallback_suggestion(current_layout)

        return {
            "suggested_layout": validated,
            "reasoning": reasoning,
            "confidence": 0.7,
        }

    def _fallback_suggestion(self, current_layout: list[dict]) -> dict:
        """Return the current layout as-is when LLM is unavailable."""
        return {
            "suggested_layout": current_layout,
            "reasoning": "AI suggestion unavailable — showing current layout.",
            "confidence": 0.0,
        }
