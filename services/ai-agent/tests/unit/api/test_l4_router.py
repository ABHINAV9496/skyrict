"""Wire tests for the /ai/l4 scenario endpoints (SKY-93, Commit 2).

TestClient without lifespan (no DB/Redis pools); ``get_l4_service`` is
overridden with a scripted fake so these tests cover the HTTP contract:
request validation, response mapping, the 422 boundary on compare, the
scenario JSONB output shape, and the router-level ``erp.hr.ai.planning``
enforcement (direct API hits return 403 without the key).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

from fastapi.testclient import TestClient

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.api.v1.routers import l4 as l4_router
from ai_agent.main import create_app

_TENANT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
_CALLER = {
    "user_id": uuid.UUID("11111111-1111-4111-8111-111111111111"),
    "tenant_id": _TENANT_ID,
    "token_payload": {"sub": "11111111-1111-4111-8111-111111111111"},
}

_SCENARIO_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

_FAKE_SCENARIO = {
    "id": _SCENARIO_ID,
    "name": "test scenario",
    "description": None,
    "base_as_of": "2026-01-01",
    "horizon": 12,
    "currency": "USD",
    "actions": [{"type": "salary_merit", "percent": "0.05", "effective_month": 4}],
    "projection": {
        "currency": "USD",
        "horizon": 12,
        "months": [
            {
                "month": m,
                "headcount": 10,
                "salary_cost": "50000.00",
                "benefit_cost": "5000.00",
                "total_cost": "55000.00",
            }
            for m in range(1, 13)
        ],
        "salary_total": "600000.00",
        "benefit_total": "60000.00",
        "grand_total": "660000.00",
    },
    "created_by": str(_CALLER["user_id"]),
    "created_at": "2026-09-12T14:30:00",
}


class _FakeL4Service:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> dict:
        self.create_calls.append(kwargs)
        return dict(_FAKE_SCENARIO)

    async def list_scenarios(self, *, tenant_id: uuid.UUID) -> list[dict]:
        return [dict(_FAKE_SCENARIO)]

    async def get(
        self, *, tenant_id: uuid.UUID, scenario_id: uuid.UUID, user_id: uuid.UUID | None = None
    ) -> dict:
        return dict(_FAKE_SCENARIO)

    async def compare(
        self,
        *,
        tenant_id: uuid.UUID,
        scenario_ids: list[uuid.UUID],
        user_id: uuid.UUID | None = None,
    ) -> list[dict]:
        return [dict(_FAKE_SCENARIO) for _ in scenario_ids]


def _app(
    fake_service: _FakeL4Service | None = None,
    monkeypatch: pytest.MonkeyPatch | None = None,
    *,
    permission_override: bool = True,
    perm_rows: list[list[str]] | None = None,
) -> TestClient:
    if monkeypatch is not None:
        # Tenant middleware resolves the slug against Postgres; bypass it (its
        # own tests cover it) - same seam as the other API unit tests.
        monkeypatch.setattr(
            "ai_agent.api.middleware.is_tenant_required_path",
            lambda _path: False,
        )
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _CALLER
    app.dependency_overrides[get_db] = lambda: (
        _FakePermSession(perm_rows)
        if perm_rows is not None
        else None
    )
    if permission_override:
        app.dependency_overrides[l4_router._require_hr_ai_planning] = lambda: None
    app.dependency_overrides[l4_router.get_l4_service] = lambda: fake_service or _FakeL4Service()
    return TestClient(app, raise_server_exceptions=True)


class _FakePermSession:
    """Scripted AsyncSession stand-in that answers the RBAC join result."""

    def __init__(self, rows: list[list[str]]) -> None:
        self._rows = rows

    async def execute(self, _stmt: Any) -> _FakePermResult:
        return _FakePermResult(self._rows)


class _FakePermResult:
    def __init__(self, rows: list[list[str]]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeScalars:
    def __init__(self, rows: list[list[str]]) -> None:
        self._rows = rows

    def all(self) -> list[list[str]]:
        return self._rows


class TestCreateScenario:
    def test_post_creates_and_returns_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeL4Service()
        client = _app(fake, monkeypatch=monkeypatch)

        response = client.post(
            "/api/v1/ai/l4/scenarios",
            json={
                "name": "my scenario",
                "base_as_of": "2026-01-01",
                "horizon": 12,
                "actions": [{"type": "salary_merit", "percent": "0.05", "effective_month": 4}],
            },
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == str(_SCENARIO_ID)
        assert payload["name"] == "test scenario"
        assert payload["currency"] == "USD"
        assert "projection" in payload
        assert len(payload["projection"]["months"]) == 12
        assert fake.create_calls[0]["name"] == "my scenario"
        assert fake.create_calls[0]["horizon"] == 12

    def test_post_validates_required_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _app(monkeypatch=monkeypatch)

        response = client.post(
            "/api/v1/ai/l4/scenarios",
            json={"base_as_of": "2026-01-01"},
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 422


class TestListScenarios:
    def test_get_list_returns_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _app(monkeypatch=monkeypatch)

        response = client.get(
            "/api/v1/ai/l4/scenarios",
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        assert items[0]["id"] == str(_SCENARIO_ID)


class TestGetScenario:
    def test_get_by_id_returns_full_scenario(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _app(monkeypatch=monkeypatch)

        response = client.get(
            f"/api/v1/ai/l4/scenarios/{_SCENARIO_ID}",
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 200
        assert response.json()["id"] == str(_SCENARIO_ID)


class TestCompareScenarios:
    def test_compare_returns_multiple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        id2 = uuid.uuid4()
        client = _app(monkeypatch=monkeypatch)

        response = client.get(
            f"/api/v1/ai/l4/scenarios/compare?ids={_SCENARIO_ID}&ids={id2}",
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 200
        items = response.json()
        assert len(items) == 2

    def test_compare_rejects_single_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _app(monkeypatch=monkeypatch)

        response = client.get(
            f"/api/v1/ai/l4/scenarios/compare?ids={_SCENARIO_ID}",
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 422

    def test_compare_rejects_more_than_three(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _app(monkeypatch=monkeypatch)
        ids = "&".join(f"ids={uuid.uuid4()}" for _ in range(4))

        response = client.get(
            f"/api/v1/ai/l4/scenarios/compare?ids={_SCENARIO_ID}&{ids}",
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 422
        assert "at most 3" in response.json()["detail"]


class _PermDeniedApp:
    """The L4 router must 403 on a direct API hit without erp.hr.ai.planning."""

    def test_endpoints_denied_without_permission(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _app(
            monkeypatch=monkeypatch,
            permission_override=False,
            perm_rows=[],
        )
        headers = {"authorization": "Bearer t"}
        body = {
            "name": "x",
            "base_as_of": "2026-01-01",
            "horizon": 12,
            "actions": [{"type": "salary_merit", "percent": "0.05", "effective_month": 4}],
        }

        for method, url in (
            ("POST", "/api/v1/ai/l4/scenarios"),
            ("GET", "/api/v1/ai/l4/scenarios"),
            ("GET", f"/api/v1/ai/l4/scenarios/compare?ids={_SCENARIO_ID}&ids={uuid.uuid4()}"),
            ("GET", f"/api/v1/ai/l4/scenarios/{_SCENARIO_ID}"),
        ):
            response = client.request(method, url, headers=headers, json=body if method == "POST" else None)
            assert response.status_code == 403, f"{method} {url}"

    def test_granted_by_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _app(
            monkeypatch=monkeypatch,
            permission_override=False,
            perm_rows=[["erp.hr.ai.planning"]],
        )

        response = client.get(
            "/api/v1/ai/l4/scenarios",
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 200

    def test_granted_by_owner_wildcard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _app(
            monkeypatch=monkeypatch,
            permission_override=False,
            perm_rows=[["*"]],
        )

        response = client.post(
            "/api/v1/ai/l4/scenarios",
            json={
                "name": "owner scenario",
                "base_as_of": "2026-01-01",
                "horizon": 12,
                "actions": [{"type": "salary_merit", "percent": "0.05", "effective_month": 4}],
            },
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 200
