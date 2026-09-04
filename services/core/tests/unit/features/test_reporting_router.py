"""Unit tests for the ``/api/v1/dashboards`` router."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.api.deps import get_current_user
from core.db.session import get_db
from core.features.reporting import router as reporting_router


def _app_with_mocks() -> TestClient:
    app = FastAPI()
    app.include_router(reporting_router.router, prefix="/api/v1")

    # Override current_user dep
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": user_id,
        "tenant_id": tenant_id,
    }

    # Override db session dep
    mock_session = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_session

    # Override service dep
    mock_service = AsyncMock()
    mock_service.resolve_layout.return_value = {
        "layout": [{"id": "attention_strip", "order": 0, "cols": 4, "visible": True}],
        "updated_at": "2026-09-02T10:00:00Z",
    }
    mock_service.save_user_layout.return_value = {
        "layout": [{"id": "attention_strip", "order": 0, "cols": 4, "visible": True}],
        "updated_at": "2026-09-02T10:05:00Z",
    }
    mock_service.reset_user_layout.return_value = True
    mock_service.record_events.return_value = 1

    app.dependency_overrides[reporting_router._get_service] = lambda: mock_service

    return TestClient(app)


def test_get_my_layout_route_200() -> None:
    client = _app_with_mocks()
    response = client.get("/api/v1/dashboards/me")
    assert response.status_code == 200, response.text
    data = response.json()
    assert "layout" in data
    assert len(data["layout"]) == 1
    assert data["layout"][0]["id"] == "attention_strip"


def test_save_my_layout_route_200() -> None:
    client = _app_with_mocks()
    payload = {
        "layout": [{"id": "attention_strip", "order": 0, "cols": 4, "visible": True}],
    }
    response = client.put("/api/v1/dashboards/me", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert "layout" in data


def test_reset_my_layout_route_204() -> None:
    client = _app_with_mocks()
    response = client.post("/api/v1/dashboards/me/reset")
    assert response.status_code == 204


def test_record_my_events_route_201() -> None:
    client = _app_with_mocks()
    payload = {
        "events": [{"widget_id": "attention_strip", "event": "open"}],
    }
    response = client.post("/api/v1/dashboards/me/events", json=payload)
    assert response.status_code == 201
    assert response.json() == {"recorded": 1}
