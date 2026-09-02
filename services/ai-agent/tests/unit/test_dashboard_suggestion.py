"""Unit tests for the dashboard layout suggestion service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agent.features.dashboard_suggestion.service import DashboardSuggestionService


@pytest.fixture
def mock_llm_router() -> MagicMock:
    router = MagicMock()
    router.has_providers = True
    return router


@pytest.fixture
def service(mock_llm_router: MagicMock) -> DashboardSuggestionService:
    return DashboardSuggestionService(llm_router=mock_llm_router)


@pytest.mark.asyncio
async def test_suggest_returns_current_layout_when_no_providers() -> None:
    router = MagicMock()
    router.has_providers = False

    svc = DashboardSuggestionService(llm_router=router)

    current_layout = [
        {"id": "ai_digest", "order": 0, "cols": 4, "visible": True},
        {"id": "erp_overview", "order": 1, "cols": 2, "visible": True},
    ]

    result = await svc.suggest(
        current_layout=current_layout,
        event_summary=[],
    )

    assert result["suggested_layout"] == current_layout
    assert result["confidence"] == 0.0
    assert "unavailable" in result["reasoning"].lower()


@pytest.mark.asyncio
async def test_suggest_returns_current_layout_on_llm_failure(
    service: DashboardSuggestionService, mock_llm_router: MagicMock
) -> None:
    mock_llm_router.complete = AsyncMock(side_effect=Exception("LLM unavailable"))

    current_layout = [
        {"id": "ai_digest", "order": 0, "cols": 4, "visible": True},
    ]

    result = await service.suggest(
        current_layout=current_layout,
        event_summary=[],
    )

    assert result["suggested_layout"] == current_layout
    assert result["confidence"] == 0.0


@pytest.mark.asyncio
async def test_suggest_parses_valid_llm_response(
    service: DashboardSuggestionService, mock_llm_router: MagicMock
) -> None:
    llm_response = MagicMock()
    llm_response.text = '{"layout": [{"id": "ai_digest", "order": 0, "cols": 4, "visible": true}, {"id": "erp_overview", "order": 1, "cols": 2, "visible": false}], "reasoning": "User uses digest daily but ignores overview."}'

    mock_llm_router.complete = AsyncMock(return_value=llm_response)

    current_layout = [
        {"id": "ai_digest", "order": 0, "cols": 4, "visible": True},
        {"id": "erp_overview", "order": 1, "cols": 2, "visible": True},
    ]

    result = await service.suggest(
        current_layout=current_layout,
        event_summary=[],
    )

    assert len(result["suggested_layout"]) == 2
    assert result["suggested_layout"][0]["id"] == "ai_digest"
    assert result["suggested_layout"][1]["visible"] is False
    assert "daily" in result["reasoning"].lower()
    assert result["confidence"] == 0.7


@pytest.mark.asyncio
async def test_suggest_filters_invalid_widget_ids(
    service: DashboardSuggestionService, mock_llm_router: MagicMock
) -> None:
    llm_response = MagicMock()
    llm_response.text = '{"layout": [{"id": "ai_digest", "order": 0, "cols": 4, "visible": true}, {"id": "nonexistent_widget", "order": 1, "cols": 2, "visible": true}], "reasoning": "Keep digest."}'

    mock_llm_router.complete = AsyncMock(return_value=llm_response)

    current_layout = [
        {"id": "ai_digest", "order": 0, "cols": 4, "visible": True},
        {"id": "erp_overview", "order": 1, "cols": 2, "visible": True},
    ]

    result = await service.suggest(
        current_layout=current_layout,
        event_summary=[],
    )

    # nonexistent_widget should be filtered out
    assert len(result["suggested_layout"]) == 1
    assert result["suggested_layout"][0]["id"] == "ai_digest"


@pytest.mark.asyncio
async def test_suggest_clamps_cols_to_valid_range(
    service: DashboardSuggestionService, mock_llm_router: MagicMock
) -> None:
    llm_response = MagicMock()
    llm_response.text = '{"layout": [{"id": "ai_digest", "order": 0, "cols": 10, "visible": true}], "reasoning": "Max width."}'

    mock_llm_router.complete = AsyncMock(return_value=llm_response)

    current_layout = [
        {"id": "ai_digest", "order": 0, "cols": 4, "visible": True},
    ]

    result = await service.suggest(
        current_layout=current_layout,
        event_summary=[],
    )

    assert result["suggested_layout"][0]["cols"] == 4  # clamped from 10


@pytest.mark.asyncio
async def test_suggest_handles_markdown_fenced_response(
    service: DashboardSuggestionService, mock_llm_router: MagicMock
) -> None:
    llm_response = MagicMock()
    llm_response.text = '```json\n{"layout": [{"id": "ai_digest", "order": 0, "cols": 4, "visible": true}], "reasoning": "Keep digest."}\n```'

    mock_llm_router.complete = AsyncMock(return_value=llm_response)

    current_layout = [
        {"id": "ai_digest", "order": 0, "cols": 4, "visible": True},
    ]

    result = await service.suggest(
        current_layout=current_layout,
        event_summary=[],
    )

    assert len(result["suggested_layout"]) == 1


@pytest.mark.asyncio
async def test_suggest_handles_unparseable_response(
    service: DashboardSuggestionService, mock_llm_router: MagicMock
) -> None:
    llm_response = MagicMock()
    llm_response.text = "I cannot suggest a layout."

    mock_llm_router.complete = AsyncMock(return_value=llm_response)

    current_layout = [
        {"id": "ai_digest", "order": 0, "cols": 4, "visible": True},
    ]

    result = await service.suggest(
        current_layout=current_layout,
        event_summary=[],
    )

    # Falls back to current layout
    assert result["suggested_layout"] == current_layout
    assert result["confidence"] == 0.0
