"""Unit tests for the CRM transcript wire endpoints (SKY-91).

The app is exercised through TestClient without lifespan (no DB/Redis pools),
with auth stubbed to a fixed caller and the CRM AI service replaced by a
scripted fake. These tests cover the wire contract: payload validation,
service-argument wiring, response mapping (sentiment enum coercion), the 404
empty-history shape, and 503 sanitization when no AI provider is configured.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from fastapi.testclient import TestClient

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.api.v1.routers import crm as crm_router
from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.features.crm.transcript_analysis import TranscriptAnalysis
from ai_agent.main import create_app

if TYPE_CHECKING:
    import pytest

_TENANT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
_ACTIVITY_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
_CALLER = {
    "user_id": uuid.UUID("11111111-1111-4111-8111-111111111111"),
    "tenant_id": _TENANT_ID,
    "token_payload": {"sub": "11111111-1111-4111-8111-111111111111"},
}

_ANALYSIS = TranscriptAnalysis(
    summary="The customer asked about pricing and the timeline.",
    objection_score=45,
    objections=["price is too high", "timeline is too aggressive"],
    next_best_action="send a revised quote with a phased rollout",
    sentiment="mixed",
    key_topics=["pricing", "timeline", "implementation"],
    confidence=0.7,
)

_ROW = SimpleNamespace(
    activity_id=_ACTIVITY_ID,
    summary=_ANALYSIS.summary,
    objection_score=_ANALYSIS.objection_score,
    objections=list(_ANALYSIS.objections),
    next_best_action=_ANALYSIS.next_best_action,
    sentiment=_ANALYSIS.sentiment,
    key_topics=list(_ANALYSIS.key_topics),
    confidence=_ANALYSIS.confidence,
    model_version="v1",
    analyzed_at=datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC),
)


class _NullSession:
    """Stands in for the async session (the service is fully faked away)."""

    async def execute(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("service is faked; session must not be touched")

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


class FakeCrmAiService:
    """Scripted stand-in for CrmAiService recording every call."""

    def __init__(
        self,
        *,
        result: TranscriptAnalysis | None = None,
        row: Any = None,
        analyze_error: Exception | None = None,
    ) -> None:
        self._result = result
        self._row = row
        self._analyze_error = analyze_error
        self.analyze_calls: list[dict[str, Any]] = []
        self.latest_calls: list[dict[str, Any]] = []

    async def analyze_transcript(
        self,
        *,
        tenant_id: uuid.UUID,
        activity_id: uuid.UUID,
        user_id: uuid.UUID,
        transcript: str,
    ) -> TranscriptAnalysis:
        self.analyze_calls.append(
            {
                "tenant_id": tenant_id,
                "activity_id": activity_id,
                "user_id": user_id,
                "transcript": transcript,
            }
        )
        if self._analyze_error is not None:
            raise self._analyze_error
        return self._result or _ANALYSIS

    async def latest_transcript_analysis(
        self,
        *,
        tenant_id: uuid.UUID,
        activity_id: uuid.UUID,
    ) -> Any:
        self.latest_calls.append({"tenant_id": tenant_id, "activity_id": activity_id})
        return self._row


def _app_with_service(
    monkeypatch: pytest.MonkeyPatch,
    service: FakeCrmAiService,
) -> TestClient:
    # The tenant middleware resolves the slug against Postgres; bypass it
    # (its behaviour has its own tests) and stub the auth dependency with a
    # fixed caller instead - same seam as the other API unit tests.
    monkeypatch.setattr("ai_agent.api.middleware.is_tenant_required_path", lambda _path: False)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _CALLER
    app.dependency_overrides[get_db] = lambda: _NullSession()
    app.dependency_overrides[crm_router.get_crm_service] = lambda: service
    return TestClient(app, raise_server_exceptions=True)


class TestPostTranscriptAnalysis:
    def test_analyzes_and_maps_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _app_with_service(monkeypatch, FakeCrmAiService())

        response = client.post(
            f"/api/v1/ai/crm/activities/{_ACTIVITY_ID}/transcript",
            json={"transcript": "Hello, we need a quote."},
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["activity_id"] == str(_ACTIVITY_ID)
        assert payload["summary"] == _ANALYSIS.summary
        assert payload["objection_score"] == 45
        assert payload["objections"] == _ANALYSIS.objections
        assert payload["next_best_action"] == _ANALYSIS.next_best_action
        assert payload["sentiment"] == "mixed"
        assert payload["key_topics"] == _ANALYSIS.key_topics
        assert payload["confidence"] == 0.7
        assert payload["model_version"] == "v1"
        assert "analyzed_at" in payload

    def test_passes_caller_identity_and_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = FakeCrmAiService()
        client = _app_with_service(monkeypatch, service)

        client.post(
            f"/api/v1/ai/crm/activities/{_ACTIVITY_ID}/transcript",
            json={"transcript": "quote request"},
            headers={"authorization": "Bearer t"},
        )

        assert service.analyze_calls == [
            {
                "tenant_id": _TENANT_ID,
                "activity_id": _ACTIVITY_ID,
                "user_id": _CALLER["user_id"],
                "transcript": "quote request",
            }
        ]

    def test_no_provider_is_sanitized_503(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = FakeCrmAiService(analyze_error=AiUnavailableError("No AI provider is configured"))
        client = _app_with_service(monkeypatch, service)

        response = client.post(
            f"/api/v1/ai/crm/activities/{_ACTIVITY_ID}/transcript",
            json={"transcript": "quote request"},
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 503
        # The stable problem type is exposed, provider internals never leak.
        assert "problems/ai-unavailable" in response.text

    def test_missing_transcript_rejected_without_calling_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = FakeCrmAiService()
        client = _app_with_service(monkeypatch, service)

        response = client.post(
            f"/api/v1/ai/crm/activities/{_ACTIVITY_ID}/transcript",
            json={},
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 422
        assert service.analyze_calls == []

    def test_empty_transcript_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = FakeCrmAiService()
        client = _app_with_service(monkeypatch, service)

        response = client.post(
            f"/api/v1/ai/crm/activities/{_ACTIVITY_ID}/transcript",
            json={"transcript": ""},
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 422
        assert service.analyze_calls == []


class TestGetTranscriptAnalysis:
    def test_returns_latest_persisted_analysis(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _app_with_service(monkeypatch, FakeCrmAiService(row=_ROW))

        response = client.get(
            f"/api/v1/ai/crm/activities/{_ACTIVITY_ID}/transcript",
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["activity_id"] == str(_ACTIVITY_ID)
        assert payload["summary"] == _ANALYSIS.summary
        assert payload["objection_score"] == 45
        assert payload["sentiment"] == "mixed"
        assert payload["model_version"] == "v1"
        assert payload["analyzed_at"] == "2026-09-11T12:00:00Z"

    def test_scopes_read_by_tenant_and_activity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = FakeCrmAiService(row=_ROW)
        client = _app_with_service(monkeypatch, service)

        client.get(
            f"/api/v1/ai/crm/activities/{_ACTIVITY_ID}/transcript",
            headers={"authorization": "Bearer t"},
        )

        assert service.latest_calls == [{"tenant_id": _TENANT_ID, "activity_id": _ACTIVITY_ID}]

    def test_missing_analysis_is_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _app_with_service(monkeypatch, FakeCrmAiService(row=None))

        response = client.get(
            f"/api/v1/ai/crm/activities/{_ACTIVITY_ID}/transcript",
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# CRM anomaly management (SKY-91)
# ---------------------------------------------------------------------------

_ANOMALY_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_OPPORTUNITY_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

_ANOMALY_ROW = SimpleNamespace(
    id=_ANOMALY_ID,
    opportunity_id=_OPPORTUNITY_ID,
    rule_id="stage_stall",
    severity="critical",
    status="open",
    title="Deal stuck",
    description="No movement for 45 days.",
    context={"days_in_stage": 45},
    detected_at=datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC),
)

_RESOLVED_ROW = SimpleNamespace(
    id=_ANOMALY_ID,
    opportunity_id=_OPPORTUNITY_ID,
    rule_id="stage_stall",
    severity="critical",
    status="resolved",
    title="Deal stuck",
    description="No movement for 45 days.",
    context={"days_in_stage": 45},
    detected_at=datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC),
)

_DISMISSED_ROW = SimpleNamespace(
    id=_ANOMALY_ID,
    opportunity_id=_OPPORTUNITY_ID,
    rule_id="stage_stall",
    severity="critical",
    status="dismissed",
    title="Deal stuck",
    description="No movement for 45 days.",
    context={"days_in_stage": 45},
    detected_at=datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC),
)


class FakeCrmAnomalyService:
    """Scripted stand-in recording anomaly-management calls."""

    def __init__(
        self,
        *,
        items: list[Any] | None = None,
        resolve_row: Any = None,
        dismiss_row: Any = None,
        resolve_error: Exception | None = None,
        dismiss_error: Exception | None = None,
    ) -> None:
        self._items = items or []
        self._resolve_row = resolve_row
        self._dismiss_row = dismiss_row
        self._resolve_error = resolve_error
        self._dismiss_error = dismiss_error
        self.list_calls: list[dict[str, Any]] = []
        self.resolve_calls: list[dict[str, Any]] = []
        self.dismiss_calls: list[dict[str, Any]] = []

    async def list_open_crm_anomalies(self, *, tenant_id: uuid.UUID) -> list[Any]:
        self.list_calls.append({"tenant_id": tenant_id})
        return self._items

    async def resolve_crm_anomaly(
        self, *, tenant_id: uuid.UUID, anomaly_id: uuid.UUID, user_id: uuid.UUID
    ) -> Any:
        self.resolve_calls.append(
            {"tenant_id": tenant_id, "anomaly_id": anomaly_id, "user_id": user_id}
        )
        if self._resolve_error is not None:
            raise self._resolve_error
        return self._resolve_row or _RESOLVED_ROW

    async def dismiss_crm_anomaly(
        self, *, tenant_id: uuid.UUID, anomaly_id: uuid.UUID, user_id: uuid.UUID
    ) -> Any:
        self.dismiss_calls.append(
            {"tenant_id": tenant_id, "anomaly_id": anomaly_id, "user_id": user_id}
        )
        if self._dismiss_error is not None:
            raise self._dismiss_error
        return self._dismiss_row or _DISMISSED_ROW


class TestListCrmAnomalies:
    def test_lists_open_anomalies_for_tenant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = FakeCrmAnomalyService(items=[_ANOMALY_ROW])
        client = _app_with_service(monkeypatch, service)

        response = client.get(
            "/api/v1/ai/crm/anomalies",
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 1
        assert payload[0]["id"] == str(_ANOMALY_ID)
        assert payload[0]["opportunity_id"] == str(_OPPORTUNITY_ID)
        assert payload[0]["rule_id"] == "stage_stall"
        assert payload[0]["severity"] == "critical"
        assert payload[0]["status"] == "open"
        assert payload[0]["title"] == "Deal stuck"
        assert payload[0]["context"] == {"days_in_stage": 45}
        assert payload[0]["detected_at"] == "2026-09-11T12:00:00Z"
        assert service.list_calls == [{"tenant_id": _TENANT_ID}]

    def test_empty_feed_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _app_with_service(monkeypatch, FakeCrmAnomalyService(items=[]))

        response = client.get(
            "/api/v1/ai/crm/anomalies",
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 200
        assert response.json() == []


class TestResolveCrmAnomaly:
    def test_resolves_and_returns_updated_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = FakeCrmAnomalyService()
        client = _app_with_service(monkeypatch, service)

        response = client.post(
            f"/api/v1/ai/crm/anomalies/{_ANOMALY_ID}/resolve",
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == str(_ANOMALY_ID)
        assert payload["status"] == "resolved"
        assert service.resolve_calls == [
            {
                "tenant_id": _TENANT_ID,
                "anomaly_id": _ANOMALY_ID,
                "user_id": _CALLER["user_id"],
            }
        ]

    def test_missing_anomaly_is_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = FakeCrmAnomalyService(resolve_error=ValueError("CRM anomaly not found"))
        client = _app_with_service(monkeypatch, service)

        response = client.post(
            f"/api/v1/ai/crm/anomalies/{_ANOMALY_ID}/resolve",
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 404
        assert "CRM anomaly not found" in response.text


class TestDismissCrmAnomaly:
    def test_dismisses_and_returns_updated_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = FakeCrmAnomalyService()
        client = _app_with_service(monkeypatch, service)

        response = client.post(
            f"/api/v1/ai/crm/anomalies/{_ANOMALY_ID}/dismiss",
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == str(_ANOMALY_ID)
        assert payload["status"] == "dismissed"
        assert service.dismiss_calls == [
            {
                "tenant_id": _TENANT_ID,
                "anomaly_id": _ANOMALY_ID,
                "user_id": _CALLER["user_id"],
            }
        ]

    def test_missing_anomaly_is_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        service = FakeCrmAnomalyService(dismiss_error=ValueError("CRM anomaly not found"))
        client = _app_with_service(monkeypatch, service)

        response = client.post(
            f"/api/v1/ai/crm/anomalies/{_ANOMALY_ID}/dismiss",
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 404
        assert "CRM anomaly not found" in response.text
