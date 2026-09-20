"""Unit tests for the dashboard layout suggestion service."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agent.features.dashboard_suggestion.gateway import EventSummary, WidgetTelemetry
from ai_agent.features.dashboard_suggestion.service import DashboardSuggestionService

_TENANT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")

_CURRENT_LAYOUT = [
    {"id": "ai_digest", "order": 0, "cols": 4, "visible": True},
    {"id": "erp_overview", "order": 1, "cols": 2, "visible": True},
]


def _summary(*, suggestion_ready: bool) -> EventSummary:
    return EventSummary(
        items=[
            WidgetTelemetry(widget_id="ai_digest", total_events=60, distinct_events=2),
            WidgetTelemetry(widget_id="erp_overview", total_events=2, distinct_events=1),
        ],
        suggestion_ready=suggestion_ready,
    )


@pytest.fixture
def mock_llm_router() -> MagicMock:
    router = MagicMock()
    router.has_providers = True
    return router


@pytest.fixture
def mock_gateway() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(mock_llm_router: MagicMock, mock_gateway: AsyncMock) -> DashboardSuggestionService:
    return DashboardSuggestionService(llm_router=mock_llm_router, gateway=mock_gateway)


@pytest.mark.asyncio
async def test_insufficient_data_skips_llm_and_keeps_layout(
    service: DashboardSuggestionService,
    mock_gateway: AsyncMock,
    mock_llm_router: MagicMock,
) -> None:
    mock_gateway.get_event_summary.return_value = _summary(suggestion_ready=False)

    result = await service.suggest(tenant_id=_TENANT_ID, current_layout=_CURRENT_LAYOUT)

    assert result["status"] == "insufficient_data"
    assert result["suggested_layout"] == _CURRENT_LAYOUT
    assert result["confidence"] == 0.0
    mock_llm_router.complete.assert_not_called()


@pytest.mark.asyncio
async def test_suggest_returns_current_layout_when_no_providers(
    mock_gateway: AsyncMock,
) -> None:
    router = MagicMock()
    router.has_providers = False

    svc = DashboardSuggestionService(llm_router=router, gateway=mock_gateway)
    mock_gateway.get_event_summary.return_value = _summary(suggestion_ready=True)

    result = await svc.suggest(tenant_id=_TENANT_ID, current_layout=_CURRENT_LAYOUT)

    assert result["status"] == "fallback"
    assert result["suggested_layout"] == _CURRENT_LAYOUT
    assert result["confidence"] == 0.0


@pytest.mark.asyncio
async def test_suggest_returns_current_layout_on_llm_failure(
    service: DashboardSuggestionService,
    mock_gateway: AsyncMock,
    mock_llm_router: MagicMock,
) -> None:
    mock_gateway.get_event_summary.return_value = _summary(suggestion_ready=True)
    mock_llm_router.complete = AsyncMock(side_effect=Exception("LLM unavailable"))

    result = await service.suggest(tenant_id=_TENANT_ID, current_layout=_CURRENT_LAYOUT)

    assert result["status"] == "fallback"
    assert result["suggested_layout"] == _CURRENT_LAYOUT
    assert result["confidence"] == 0.0


@pytest.mark.asyncio
async def test_suggest_parses_valid_llm_response(
    service: DashboardSuggestionService,
    mock_gateway: AsyncMock,
    mock_llm_router: MagicMock,
) -> None:
    mock_gateway.get_event_summary.return_value = _summary(suggestion_ready=True)
    llm_response = MagicMock()
    llm_response.text = """{"layout": [
        {"id": "ai_digest", "order": 0, "cols": 4, "visible": true},
        {"id": "erp_overview", "order": 1, "cols": 2, "visible": false}
    ], "reasoning": "User uses digest daily but ignores overview."}"""

    mock_llm_router.complete = AsyncMock(return_value=llm_response)

    result = await service.suggest(tenant_id=_TENANT_ID, current_layout=_CURRENT_LAYOUT)

    assert result["status"] == "suggested"
    assert len(result["suggested_layout"]) == 2
    assert result["suggested_layout"][0]["id"] == "ai_digest"
    assert result["suggested_layout"][1]["visible"] is False
    assert "daily" in result["reasoning"].lower()
    assert result["confidence"] == 0.7


@pytest.mark.asyncio
async def test_suggest_filters_invalid_widget_ids(
    service: DashboardSuggestionService,
    mock_gateway: AsyncMock,
    mock_llm_router: MagicMock,
) -> None:
    mock_gateway.get_event_summary.return_value = _summary(suggestion_ready=True)
    llm_response = MagicMock()
    llm_response.text = """{"layout": [
        {"id": "ai_digest", "order": 0, "cols": 4, "visible": true},
        {"id": "nonexistent_widget", "order": 1, "cols": 2, "visible": true}
    ], "reasoning": "Keep digest."}"""

    mock_llm_router.complete = AsyncMock(return_value=llm_response)

    result = await service.suggest(tenant_id=_TENANT_ID, current_layout=_CURRENT_LAYOUT)

    assert len(result["suggested_layout"]) == 1
    assert result["suggested_layout"][0]["id"] == "ai_digest"


@pytest.mark.asyncio
async def test_suggest_clamps_cols_to_valid_range(
    service: DashboardSuggestionService,
    mock_gateway: AsyncMock,
    mock_llm_router: MagicMock,
) -> None:
    mock_gateway.get_event_summary.return_value = _summary(suggestion_ready=True)
    llm_response = MagicMock()
    llm_response.text = '{"layout": [{"id": "ai_digest", "order": 0, "cols": 10, "visible": true}], "reasoning": "Max width."}'

    mock_llm_router.complete = AsyncMock(return_value=llm_response)

    current_layout = [{"id": "ai_digest", "order": 0, "cols": 4, "visible": True}]

    result = await service.suggest(tenant_id=_TENANT_ID, current_layout=current_layout)

    assert result["suggested_layout"][0]["cols"] == 4


@pytest.mark.asyncio
async def test_suggest_handles_markdown_fenced_response(
    service: DashboardSuggestionService,
    mock_gateway: AsyncMock,
    mock_llm_router: MagicMock,
) -> None:
    mock_gateway.get_event_summary.return_value = _summary(suggestion_ready=True)
    llm_response = MagicMock()
    llm_response.text = '```json\n{"layout": [{"id": "ai_digest", "order": 0, "cols": 4, "visible": true}], "reasoning": "Keep digest."}\n```'

    mock_llm_router.complete = AsyncMock(return_value=llm_response)

    current_layout = [{"id": "ai_digest", "order": 0, "cols": 4, "visible": True}]

    result = await service.suggest(tenant_id=_TENANT_ID, current_layout=current_layout)

    assert len(result["suggested_layout"]) == 1


@pytest.mark.asyncio
async def test_suggest_handles_unparseable_response(
    service: DashboardSuggestionService,
    mock_gateway: AsyncMock,
    mock_llm_router: MagicMock,
) -> None:
    mock_gateway.get_event_summary.return_value = _summary(suggestion_ready=True)
    llm_response = MagicMock()
    llm_response.text = "I cannot suggest a layout."

    mock_llm_router.complete = AsyncMock(return_value=llm_response)

    current_layout = [{"id": "ai_digest", "order": 0, "cols": 4, "visible": True}]

    result = await service.suggest(tenant_id=_TENANT_ID, current_layout=current_layout)

    assert result["status"] == "fallback"
    assert result["suggested_layout"] == current_layout
    assert result["confidence"] == 0.0
