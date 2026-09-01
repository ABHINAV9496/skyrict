"""Unit tests for the dashboard layout reporting service."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.features.reporting.repository import DashboardRepository
from core.features.reporting.service import DashboardService


@pytest.fixture
def mock_repo() -> AsyncMock:
    return AsyncMock(spec=DashboardRepository)


@pytest.fixture
def service(mock_repo: AsyncMock) -> DashboardService:
    return DashboardService(repository=mock_repo)


@pytest.mark.asyncio
async def test_resolve_layout_returns_user_override(
    service: DashboardService, mock_repo: AsyncMock
) -> None:
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    user_layout = MagicMock()
    user_layout.layout = [{"id": "ai_digest", "order": 0, "cols": 4, "visible": True}]
    user_layout.updated_at.isoformat.return_value = "2026-09-01T00:00:00"

    mock_repo.get_user_layout.return_value = user_layout

    result = await service.resolve_layout(tenant_id=tenant_id, user_id=user_id)

    assert result["source"] == "user"
    assert len(result["layout"]) == 1
    assert result["layout"][0]["id"] == "ai_digest"


@pytest.mark.asyncio
async def test_resolve_layout_falls_back_to_tenant_default(
    service: DashboardService, mock_repo: AsyncMock
) -> None:
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_repo.get_user_layout.return_value = None

    tenant_default = MagicMock()
    tenant_default.layout = [{"id": "erp_overview", "order": 0, "cols": 2, "visible": True}]
    tenant_default.updated_at.isoformat.return_value = "2026-09-01T00:00:00"

    mock_repo.get_tenant_default.return_value = tenant_default

    result = await service.resolve_layout(tenant_id=tenant_id, user_id=user_id)

    assert result["source"] == "tenant_default"
    assert len(result["layout"]) == 1


@pytest.mark.asyncio
async def test_resolve_layout_returns_empty_when_nothing_exists(
    service: DashboardService, mock_repo: AsyncMock
) -> None:
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_repo.get_user_layout.return_value = None
    mock_repo.get_tenant_default.return_value = None

    result = await service.resolve_layout(tenant_id=tenant_id, user_id=user_id)

    assert result["source"] == "empty"
    assert result["layout"] == []
    assert result["updated_at"] is None


@pytest.mark.asyncio
async def test_save_user_layout(
    service: DashboardService, mock_repo: AsyncMock
) -> None:
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    record = MagicMock()
    record.layout = [{"id": "ai_digest", "order": 0, "cols": 4, "visible": True}]
    record.updated_at.isoformat.return_value = "2026-09-01T00:00:00"

    mock_repo.upsert_user_layout.return_value = record

    result = await service.save_user_layout(
        tenant_id=tenant_id,
        user_id=user_id,
        layout=[{"id": "ai_digest", "order": 0, "cols": 4, "visible": True}],
    )

    assert len(result["layout"]) == 1
    mock_repo.upsert_user_layout.assert_called_once()


@pytest.mark.asyncio
async def test_reset_user_layout(
    service: DashboardService, mock_repo: AsyncMock
) -> None:
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_repo.delete_user_layout.return_value = True

    result = await service.reset_user_layout(
        tenant_id=tenant_id, user_id=user_id
    )

    assert result is True
    mock_repo.delete_user_layout.assert_called_once_with(
        tenant_id=tenant_id, user_id=user_id
    )


@pytest.mark.asyncio
async def test_record_events(
    service: DashboardService, mock_repo: AsyncMock
) -> None:
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_repo.record_widget_events.return_value = 3

    count = await service.record_events(
        tenant_id=tenant_id,
        user_id=user_id,
        events=[
            {"widget_id": "ai_digest", "event": "open"},
            {"widget_id": "erp_overview", "event": "open"},
            {"widget_id": "ai_digest", "event": "hide"},
        ],
    )

    assert count == 3


@pytest.mark.asyncio
async def test_has_enough_events_true(
    service: DashboardService, mock_repo: AsyncMock
) -> None:
    tenant_id = uuid.uuid4()

    mock_repo.get_widget_event_summary.return_value = [
        {"widget_id": "ai_digest", "total_events": 55, "distinct_events": 2},
    ]

    result = await service.has_enough_events(tenant_id=tenant_id)

    assert result is True


@pytest.mark.asyncio
async def test_has_enough_events_false(
    service: DashboardService, mock_repo: AsyncMock
) -> None:
    tenant_id = uuid.uuid4()

    mock_repo.get_widget_event_summary.return_value = [
        {"widget_id": "ai_digest", "total_events": 10, "distinct_events": 2},
    ]

    result = await service.has_enough_events(tenant_id=tenant_id)

    assert result is False
