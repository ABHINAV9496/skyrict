"""Dashboard layout suggestion router.

Endpoint:
    POST /api/v1/ai/dashboards/suggest - AI-powered layout suggestion
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ai_agent.features.dashboard_suggestion.schemas import (
    SuggestionRequest,
    SuggestionResponse,
    WidgetLayoutItem,
)
from ai_agent.features.dashboard_suggestion.service import DashboardSuggestionService

router = APIRouter(prefix="/api/v1/ai/dashboards", tags=["ai-dashboards"])


@router.post("/suggest", response_model=SuggestionResponse)
async def suggest_layout(
    body: SuggestionRequest,
    request: Request,
) -> SuggestionResponse:
    """Request an AI-powered layout suggestion based on widget telemetry.

    The suggestion engine analyzes the user's current layout and widget
    interaction events to recommend reordering, resizing, or hiding widgets.
    """
    llm_router = request.app.state.llm_router
    service = DashboardSuggestionService(llm_router=llm_router)

    # TODO: Fetch event_summary from core service via HTTP gateway
    # For now, pass empty summary - the LLM will use layout order only.
    event_summary: list[dict[str, Any]] = []

    result = await service.suggest(
        current_layout=[item.model_dump() for item in body.current_layout],
        event_summary=event_summary,
    )

    return SuggestionResponse(
        suggested_layout=[WidgetLayoutItem(**item) for item in result["suggested_layout"]],
        reasoning=result["reasoning"],
        confidence=result["confidence"],
    )
