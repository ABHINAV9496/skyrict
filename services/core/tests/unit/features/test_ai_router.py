"""Unit tests for ``/api/v1/ai`` route-parameter validation.

Path ids must be UUIDs BEFORE anything is forwarded: FastAPI rejects any
other shape with 422 and the upstream request target only ever embeds the
canonical hyphenated form - no traversal or metacharacters can reach
ai-agent (taint cut for the CodeQL SSRF finding). Permission dependencies
and the pooled client are overridden; transport behaviour lives in
test_ai_proxy.py. The narrator (SKY-63) routes also exercise their strict
AND-permission gate against a stubbed RBAC resolver.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.api import deps as api_deps
from core.api.deps import (
    get_crm_workspace_service,
    get_current_scope,
    get_current_user,
    get_db,
)
from core.core.exceptions import SkyrictError, skyrict_error_handler
from core.core.permissions import (
    ERP_AI_COACHING_READ,
    ERP_AI_COACHING_REVIEW,
    ERP_AI_GUARDIAN_READ,
    ERP_AI_GUARDIAN_REVIEW,
    ERP_AI_INVOKE,
    ERP_AI_L3_REFRESH,
    ERP_AI_NARRATOR_REFRESH,
    ERP_CRM_READ,
    ERP_CRM_WRITE,
    ERP_FINANCE_READ,
    ERP_HR_AI_MANAGEMENT,
    ERP_INVENTORY_READ,
    ERP_REPORTS_CREATE,
    ERP_REPORTS_READ,
    ERP_SALES_READ,
)
from core.domain.value_objects import DataScope
from core.features.ai import router as ai_router


def _app_with_recorder(
    seen: list[httpx.Request],
    fake_workspace: object | None = None,
) -> TestClient:
    """App with auth deps stubbed and an upstream that records every call.

    ``fake_workspace`` replaces the CRM workspace service used by the SKY-91
    transcript POST (which stores the transcript BEFORE forwarding). Existing
    routes never resolve it, so the default stub is inert for them. The
    stubbed user carries string ids because the transcript handler converts
    tenant/user to UUIDs exactly like the workspace API.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    fake_user = {
        "sub": "user-1",
        "user_id": "11111111-1111-4111-8111-111111111111",
        "tenant_id": "22222222-2222-4222-8222-222222222222",
    }
    app = FastAPI()
    app.include_router(ai_router.router, prefix="/api/v1")
    app.dependency_overrides[ai_router._require_ai_invoke] = lambda: fake_user
    app.dependency_overrides[ai_router._require_inventory_read] = lambda: fake_user
    app.dependency_overrides[ai_router._require_inventory_write] = lambda: fake_user
    app.dependency_overrides[ai_router._require_inventory_ai_approve] = lambda: fake_user
    app.dependency_overrides[ai_router._require_narrator_reads] = lambda: fake_user
    app.dependency_overrides[ai_router._require_narrator_refresh] = lambda: fake_user
    app.dependency_overrides[ai_router._require_reports_read] = lambda: fake_user
    app.dependency_overrides[ai_router._require_reports_create] = lambda: fake_user
    app.dependency_overrides[ai_router._require_crm_read] = lambda: fake_user
    app.dependency_overrides[ai_router._require_crm_write] = lambda: fake_user
    app.dependency_overrides[ai_router._require_coaching_read] = lambda: fake_user
    app.dependency_overrides[ai_router._require_coaching_review] = lambda: fake_user
    app.dependency_overrides[ai_router._require_guardian_read] = lambda: fake_user
    app.dependency_overrides[ai_router._require_guardian_review] = lambda: fake_user
    app.dependency_overrides[get_current_scope] = lambda: (DataScope.ALL, None)
    app.dependency_overrides[get_crm_workspace_service] = lambda: fake_workspace or _NoOpWorkspace()
    client_factory = lambda: httpx.AsyncClient(  # noqa: E731
        transport=httpx.MockTransport(handler), base_url="http://ai.test"
    )
    app.dependency_overrides[ai_router.get_ai_client] = client_factory
    return TestClient(app, raise_server_exceptions=False)


class _NoOpWorkspace:
    """Inert CRM workspace stand-in for routes that never call it."""

    async def update_activity(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("workspace service must not be called for plain relays")


class _RecordingWorkspace:
    """CRM workspace fake recorded into a shared event list."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def update_activity(self, *args: object, **kwargs: object) -> object:
        self._events.append("write")
        return {"id": "activity"}


class TestProxyPathIdsAreUuids:
    def test_valid_uuid_forwarded_canonically(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)
        suggestion_id = str(uuid.uuid4())

        response = client.post(
            f"/api/v1/ai/suggestions/{suggestion_id.upper()}/approve",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert len(seen) == 1
        # Uppercase input reaches ai-agent in canonical lowercase form.
        assert seen[0].url.path == f"/api/v1/ai/suggestions/{suggestion_id}/approve"

    def test_anomaly_escalate_forwards_uuid(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)
        anomaly_id = uuid.uuid4()

        response = client.post(
            f"/api/v1/ai/anomalies/{anomaly_id}/escalate",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert seen[0].url.path == f"/api/v1/ai/anomalies/{anomaly_id}/escalate"

    @pytest.mark.parametrize(
        ("route_template", "bad_id"),
        [
            pytest.param("/api/v1/ai/suggestions/{}/approve", "not-a-uuid", id="garbage"),
            pytest.param("/api/v1/ai/suggestions/{}/reject", "x@evil.test", id="authority-like"),
            pytest.param("/api/v1/ai/anomalies/{}/resolve", "%2e%2eadmin", id="encoded-dots"),
            pytest.param(
                "/api/v1/ai/anomalies/{}/dismiss",
                "00000000-0000-0000-0000-00000000000g",
                id="hex-with-bad-digit",
            ),
        ],
    )
    def test_malformed_id_rejected_before_any_forward(
        self, route_template: str, bad_id: str
    ) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.post(route_template.format(bad_id))

        assert response.status_code == 422
        assert seen == [], "malformed id must never reach ai-agent"

    def test_dot_segment_traversal_never_reaches_upstream(self) -> None:
        """httpx normalizes ``..`` client-side, so the request dies with 404
        at the router - the point is that NOTHING reaches ai-agent."""
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.post("/api/v1/ai/anomalies/../../admin/escalate")

        assert response.status_code in (404, 422)
        assert seen == []


class TestNarratorForwarding:
    def test_digest_get_forwards(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.get(
            "/api/v1/ai/narrator/digest?as_of=2026-08-27",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert seen[0].url.path == "/api/v1/ai/narrator/digest"
        assert seen[0].url.query == b"as_of=2026-08-27"

    def test_refresh_post_forwards(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.post(
            "/api/v1/ai/narrator/digest/refresh",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert seen[0].url.path == "/api/v1/ai/narrator/digest/refresh"


class TestSupplierRiskForwarding:
    def test_list_supplier_risk_forwards(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.get(
            "/api/v1/ai/supplier-risk",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert seen[0].url.path == "/api/v1/ai/supplier-risk"


class TestCrmDealHealthSweepForwarding:
    def test_sweep_post_forwards(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.post(
            "/api/v1/ai/crm/opportunities/sweep",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert seen[0].url.path == "/api/v1/ai/crm/opportunities/sweep"


class TestL3Narratives:
    """L3 routes forward to ai-agent only when erp.hr.ai.management is held.

    The permission dependency resolves through get_current_user + RBAC, so the
    app stubs those (mirroring TestNarratorPermissionGate) and records every
    forwarded request.
    """

    @pytest.fixture(autouse=True)
    def _patch_rbac(self, monkeypatch: pytest.MonkeyPatch) -> None:
        grants: list[str] = []
        self._grants_box = grants

        class _FakeRbac:
            def __init__(self, session: object) -> None:
                self.session = session

            async def resolve_user_permissions(
                self, *, user_id: object, tenant_id: object
            ) -> list[str]:
                return grants

        monkeypatch.setattr(api_deps, "RbacRepository", _FakeRbac)

    def _app(self, seen: list[httpx.Request]) -> TestClient:
        app = FastAPI()
        app.add_exception_handler(SkyrictError, skyrict_error_handler)
        app.include_router(ai_router.router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
        }
        app.dependency_overrides[get_db] = lambda: object()
        app.dependency_overrides[ai_router.get_ai_client] = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: (seen.append(request), httpx.Response(200, json={"ok": True}))[1]
            ),
            base_url="http://ai.test",
        )
        return TestClient(app)

    def _grant(self, *keys: str) -> None:
        self._grants_box[:] = list(keys)

    def test_get_forwards_with_query(self) -> None:
        self._grant(ERP_HR_AI_MANAGEMENT)
        seen: list[httpx.Request] = []

        response = self._app(seen).get(
            "/api/v1/ai/l3/payroll_cost?as_of=2026-09-08",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert len(seen) == 1
        assert seen[0].url.path == "/api/v1/ai/l3/payroll_cost"
        assert seen[0].url.query == b"as_of=2026-09-08"

    def test_refresh_forwards(self) -> None:
        self._grant(ERP_HR_AI_MANAGEMENT, ERP_AI_L3_REFRESH)
        seen: list[httpx.Request] = []

        response = self._app(seen).post(
            "/api/v1/ai/l3/payroll_cost/refresh",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert len(seen) == 1
        assert seen[0].url.path == "/api/v1/ai/l3/payroll_cost/refresh"

    def test_refresh_requires_dedicated_key_in_addition_to_management(self) -> None:
        self._grant(ERP_HR_AI_MANAGEMENT)
        assert self._app([]).post("/api/v1/ai/l3/payroll_cost/refresh").status_code == 403

    def test_refresh_gated_by_management_plus_refresh_key(self) -> None:
        self._grant(ERP_HR_AI_MANAGEMENT, ERP_AI_L3_REFRESH)
        assert self._app([]).post("/api/v1/ai/l3/payroll_cost/refresh").status_code == 200

    def test_without_management_denied(self) -> None:
        self._grant(ERP_AI_INVOKE, ERP_FINANCE_READ)
        assert self._app([]).get("/api/v1/ai/l3/payroll_cost").status_code == 403


class TestNarratorPermissionGate:
    """The narrator is AND-gated: invoke + every module read (refresh adds the
    dedicated key). Each authorisation is exercised with a stubbed RBAC."""

    @pytest.fixture(autouse=True)
    def _patch_rbac(self, monkeypatch: pytest.MonkeyPatch) -> None:
        grants: list[str] = []
        self._grants_box = grants

        class _FakeRbac:
            def __init__(self, session: object) -> None:
                self.session = session

            async def resolve_user_permissions(
                self, *, user_id: object, tenant_id: object
            ) -> list[str]:
                return grants

        monkeypatch.setattr(api_deps, "RbacRepository", _FakeRbac)

    def _app(self) -> TestClient:
        app = FastAPI()
        app.add_exception_handler(SkyrictError, skyrict_error_handler)
        app.include_router(ai_router.router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
        }
        app.dependency_overrides[get_db] = lambda: object()
        app.dependency_overrides[ai_router.get_ai_client] = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True})),
            base_url="http://ai.test",
        )
        return TestClient(app)

    def _grant(self, *keys: str) -> None:
        self._grants_box[:] = list(keys)

    def test_full_matrix_reads_digest(self) -> None:
        self._grant(
            ERP_AI_INVOKE,
            ERP_FINANCE_READ,
            ERP_SALES_READ,
            ERP_INVENTORY_READ,
            ERP_CRM_READ,
        )
        assert self._app().get("/api/v1/ai/narrator/digest").status_code == 200

    def test_missing_any_module_read_denied(self) -> None:
        # CRM read missing -> 403 even though invoke + other reads are held.
        self._grant(
            ERP_AI_INVOKE,
            ERP_FINANCE_READ,
            ERP_SALES_READ,
            ERP_INVENTORY_READ,
        )
        assert self._app().get("/api/v1/ai/narrator/digest").status_code == 403

    def test_missing_invoke_denied(self) -> None:
        self._grant(
            ERP_FINANCE_READ,
            ERP_SALES_READ,
            ERP_INVENTORY_READ,
            ERP_CRM_READ,
        )
        assert self._app().get("/api/v1/ai/narrator/digest").status_code == 403

    def test_refresh_needs_dedicated_key(self) -> None:
        # Full matrix but no erp.ai.narrator.refresh -> refresh denied.
        self._grant(
            ERP_AI_INVOKE,
            ERP_FINANCE_READ,
            ERP_SALES_READ,
            ERP_INVENTORY_READ,
            ERP_CRM_READ,
        )
        assert self._app().post("/api/v1/ai/narrator/digest/refresh").status_code == 403

    def test_refresh_granted_with_dedicated_key(self) -> None:
        self._grant(
            ERP_AI_INVOKE,
            ERP_FINANCE_READ,
            ERP_SALES_READ,
            ERP_INVENTORY_READ,
            ERP_CRM_READ,
            ERP_AI_NARRATOR_REFRESH,
        )
        assert self._app().post("/api/v1/ai/narrator/digest/refresh").status_code == 200


class TestReportBuilderForwarding:
    """SKY-80 proxy: generate/save must reach ai-agent unchanged."""

    def test_generate_forwards_path_and_body(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.post(
            "/api/v1/ai/report-builder/generate",
            json={"prompt": "margin by region"},
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert len(seen) == 1
        assert seen[0].url.path == "/api/v1/ai/report-builder/generate"
        assert seen[0].read() == b'{"prompt":"margin by region"}'

    def test_save_forwards_path_and_body(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.post(
            "/api/v1/ai/report-builder/save",
            json={"source_slug": "margin-by-region", "params": {}},
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert len(seen) == 1
        assert seen[0].url.path == "/api/v1/ai/report-builder/save"


class TestReportBuilderPermissionGate:
    """generate needs invoke + reports read; save adds erp.reports.create."""

    @pytest.fixture(autouse=True)
    def _patch_rbac(self, monkeypatch: pytest.MonkeyPatch) -> None:
        grants: list[str] = []
        self._grants_box = grants

        class _FakeRbac:
            def __init__(self, session: object) -> None:
                self.session = session

            async def resolve_user_permissions(
                self, *, user_id: object, tenant_id: object
            ) -> list[str]:
                return grants

        monkeypatch.setattr(api_deps, "RbacRepository", _FakeRbac)

    def _app(self) -> TestClient:
        app = FastAPI()
        app.add_exception_handler(SkyrictError, skyrict_error_handler)
        app.include_router(ai_router.router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
        }
        app.dependency_overrides[get_db] = lambda: object()
        app.dependency_overrides[ai_router.get_ai_client] = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True})),
            base_url="http://ai.test",
        )
        return TestClient(app)

    def _grant(self, *keys: str) -> None:
        self._grants_box[:] = list(keys)

    def test_generate_with_invoke_and_read(self) -> None:
        self._grant(ERP_AI_INVOKE, ERP_REPORTS_READ)
        assert self._app().post("/api/v1/ai/report-builder/generate").status_code == 200

    def test_generate_without_reports_read_denied(self) -> None:
        self._grant(ERP_AI_INVOKE)
        assert self._app().post("/api/v1/ai/report-builder/generate").status_code == 403

    def test_save_requires_create_gate(self) -> None:
        # Read alone lets you generate but not persist a new definition.
        self._grant(ERP_AI_INVOKE, ERP_REPORTS_READ)
        assert self._app().post("/api/v1/ai/report-builder/save").status_code == 403

    def test_save_with_create_gate(self) -> None:
        self._grant(ERP_AI_INVOKE, ERP_REPORTS_READ, ERP_REPORTS_CREATE)
        assert self._app().post("/api/v1/ai/report-builder/save").status_code == 200

    def test_missing_invoke_denied(self) -> None:
        self._grant(ERP_REPORTS_READ, ERP_REPORTS_CREATE)
        assert self._app().post("/api/v1/ai/report-builder/save").status_code == 403


class TestCoachingForwarding:
    """SKY-90 coaching: GET suggestions list, POST review accept/dismiss."""

    def test_list_suggestions_forwards(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.get(
            "/api/v1/ai/coaching/suggestions",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert seen[0].url.path == "/api/v1/ai/coaching/suggestions"

    def test_review_suggestion_forwards_uuid(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)
        suggestion_id = uuid.uuid4()

        response = client.post(
            f"/api/v1/ai/coaching/suggestions/{suggestion_id}/review",
            json={"status": "accepted"},
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert seen[0].url.path == f"/api/v1/ai/coaching/suggestions/{suggestion_id}/review"


class TestGuardianForwarding:
    """SKY-90 guardian: GET reports list, GET report detail, POST review."""

    def test_list_reports_forwards(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.get(
            "/api/v1/ai/guardian/reports",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert seen[0].url.path == "/api/v1/ai/guardian/reports"

    def test_get_report_detail_forwards_uuid(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)
        report_id = uuid.uuid4()

        response = client.get(
            f"/api/v1/ai/guardian/reports/{report_id}",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert seen[0].url.path == f"/api/v1/ai/guardian/reports/{report_id}"

    def test_review_report_forwards_uuid(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)
        report_id = uuid.uuid4()

        response = client.post(
            f"/api/v1/ai/guardian/reports/{report_id}/review",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert seen[0].url.path == f"/api/v1/ai/guardian/reports/{report_id}/review"


class TestCoachingPermissionGate:
    """coaching.read gates list; coaching.review gates the accept/dismiss action."""

    @pytest.fixture(autouse=True)
    def _patch_rbac(self, monkeypatch: pytest.MonkeyPatch) -> None:
        grants: list[str] = []
        self._grants_box = grants

        class _FakeRbac:
            def __init__(self, session: object) -> None:
                self.session = session

            async def resolve_user_permissions(
                self, *, user_id: object, tenant_id: object
            ) -> list[str]:
                return grants

        monkeypatch.setattr(api_deps, "RbacRepository", _FakeRbac)

    def _app(self) -> TestClient:
        app = FastAPI()
        app.add_exception_handler(SkyrictError, skyrict_error_handler)
        app.include_router(ai_router.router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
        }
        app.dependency_overrides[get_db] = lambda: object()
        app.dependency_overrides[ai_router.get_ai_client] = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True})),
            base_url="http://ai.test",
        )
        return TestClient(app)

    def _grant(self, *keys: str) -> None:
        self._grants_box[:] = list(keys)

    def test_list_with_invoke_and_read(self) -> None:
        self._grant(ERP_AI_INVOKE, ERP_AI_COACHING_READ)
        assert self._app().get("/api/v1/ai/coaching/suggestions").status_code == 200

    def test_list_without_read_denied(self) -> None:
        self._grant(ERP_AI_INVOKE)
        assert self._app().get("/api/v1/ai/coaching/suggestions").status_code == 403

    def test_review_requires_review_key(self) -> None:
        self._grant(ERP_AI_INVOKE, ERP_AI_COACHING_READ)
        assert (
            self._app().post(f"/api/v1/ai/coaching/suggestions/{uuid.uuid4()}/review").status_code
            == 403
        )

    def test_review_granted_with_review_key(self) -> None:
        self._grant(ERP_AI_INVOKE, ERP_AI_COACHING_REVIEW)
        assert (
            self._app().post(f"/api/v1/ai/coaching/suggestions/{uuid.uuid4()}/review").status_code
            == 200
        )

    def test_missing_invoke_denied(self) -> None:
        self._grant(ERP_AI_COACHING_READ)
        assert self._app().get("/api/v1/ai/coaching/suggestions").status_code == 403


class TestGuardianPermissionGate:
    """guardian.read gates list + detail; guardian.review gates the review action."""

    @pytest.fixture(autouse=True)
    def _patch_rbac(self, monkeypatch: pytest.MonkeyPatch) -> None:
        grants: list[str] = []
        self._grants_box = grants

        class _FakeRbac:
            def __init__(self, session: object) -> None:
                self.session = session

            async def resolve_user_permissions(
                self, *, user_id: object, tenant_id: object
            ) -> list[str]:
                return grants

        monkeypatch.setattr(api_deps, "RbacRepository", _FakeRbac)

    def _app(self) -> TestClient:
        app = FastAPI()
        app.add_exception_handler(SkyrictError, skyrict_error_handler)
        app.include_router(ai_router.router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
        }
        app.dependency_overrides[get_db] = lambda: object()
        app.dependency_overrides[ai_router.get_ai_client] = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True})),
            base_url="http://ai.test",
        )
        return TestClient(app)

    def _grant(self, *keys: str) -> None:
        self._grants_box[:] = list(keys)

    def test_list_with_invoke_and_read(self) -> None:
        self._grant(ERP_AI_INVOKE, ERP_AI_GUARDIAN_READ)
        assert self._app().get("/api/v1/ai/guardian/reports").status_code == 200

    def test_detail_with_invoke_and_read(self) -> None:
        self._grant(ERP_AI_INVOKE, ERP_AI_GUARDIAN_READ)
        assert self._app().get(f"/api/v1/ai/guardian/reports/{uuid.uuid4()}").status_code == 200

    def test_list_without_read_denied(self) -> None:
        self._grant(ERP_AI_INVOKE)
        assert self._app().get("/api/v1/ai/guardian/reports").status_code == 403

    def test_review_requires_review_key(self) -> None:
        self._grant(ERP_AI_INVOKE, ERP_AI_GUARDIAN_READ)
        assert (
            self._app().post(f"/api/v1/ai/guardian/reports/{uuid.uuid4()}/review").status_code
            == 403
        )

    def test_review_granted_with_review_key(self) -> None:
        self._grant(ERP_AI_INVOKE, ERP_AI_GUARDIAN_REVIEW)
        assert (
            self._app().post(f"/api/v1/ai/guardian/reports/{uuid.uuid4()}/review").status_code
            == 200
        )

    def test_missing_invoke_denied(self) -> None:
        self._grant(ERP_AI_GUARDIAN_READ)
        assert self._app().get("/api/v1/ai/guardian/reports").status_code == 403


class TestCrmTranscriptForwarding:
    """SKY-91: GET relays; POST stores the transcript FIRST, then forwards."""

    def test_get_forwards_canonical_path(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)
        activity_id = uuid.uuid4()

        response = client.get(
            f"/api/v1/ai/crm/activities/{activity_id}/transcript",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert seen[0].url.path == f"/api/v1/ai/crm/activities/{activity_id}/transcript"

    def test_post_writes_transcript_before_forwarding(self) -> None:
        seen: list[httpx.Request] = []
        events: list[str] = []
        client = _app_with_recorder(seen, fake_workspace=_RecordingWorkspace(events))
        activity_id = uuid.uuid4()

        response = client.post(
            f"/api/v1/ai/crm/activities/{activity_id}/transcript",
            json={"transcript": "customer asked about pricing"},
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert events == ["write"], "the CRM write must happen before the forward"
        assert len(seen) == 1
        assert seen[0].url.path == f"/api/v1/ai/crm/activities/{activity_id}/transcript"
        # The validated body is forwarded verbatim (compact JSON, no re-read).
        assert seen[0].read() == b'{"transcript":"customer asked about pricing"}'

    def test_write_failure_never_forwards(self) -> None:
        class _FailingWorkspace:
            async def update_activity(self, *args: object, **kwargs: object) -> object:
                raise RuntimeError("simulated write failure")

        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen, fake_workspace=_FailingWorkspace())
        activity_id = uuid.uuid4()

        response = client.post(
            f"/api/v1/ai/crm/activities/{activity_id}/transcript",
            json={"transcript": "customer asked about pricing"},
        )

        assert response.status_code == 500
        assert seen == [], "no analysis request may reach ai-agent if the write failed"

    def test_invalid_body_rejected_before_write_or_forward(self) -> None:
        seen: list[httpx.Request] = []
        events: list[str] = []
        client = _app_with_recorder(seen, fake_workspace=_RecordingWorkspace(events))
        activity_id = uuid.uuid4()

        response = client.post(
            f"/api/v1/ai/crm/activities/{activity_id}/transcript",
            json={"transcript": ""},
        )

        assert response.status_code == 422
        assert events == []
        assert seen == []

    def test_malformed_id_rejected_before_write_or_forward(self) -> None:
        seen: list[httpx.Request] = []
        events: list[str] = []
        client = _app_with_recorder(seen, fake_workspace=_RecordingWorkspace(events))

        response = client.post(
            "/api/v1/ai/crm/activities/not-a-uuid/transcript",
            json={"transcript": "customer asked about pricing"},
        )

        assert response.status_code == 422
        assert events == []
        assert seen == []


class TestCrmTranscriptPermissionGate:
    """The POST is write-like: it needs erp.ai.invoke AND erp.crm.write."""

    @pytest.fixture(autouse=True)
    def _patch_rbac(self, monkeypatch: pytest.MonkeyPatch) -> None:
        grants: list[str] = []
        self._grants_box = grants

        class _FakeRbac:
            def __init__(self, session: object) -> None:
                self.session = session

            async def resolve_user_permissions(
                self, *, user_id: object, tenant_id: object
            ) -> list[str]:
                return grants

        monkeypatch.setattr(api_deps, "RbacRepository", _FakeRbac)

    def _app(self) -> TestClient:
        app = FastAPI()
        app.add_exception_handler(SkyrictError, skyrict_error_handler)
        app.include_router(ai_router.router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": str(uuid.uuid4()),
            "tenant_id": str(uuid.uuid4()),
        }
        app.dependency_overrides[get_db] = lambda: object()
        app.dependency_overrides[get_current_scope] = lambda: (DataScope.ALL, None)
        app.dependency_overrides[get_crm_workspace_service] = lambda: _RecordingWorkspace([])
        app.dependency_overrides[ai_router.get_ai_client] = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True})),
            base_url="http://ai.test",
        )
        return TestClient(app)

    def _grant(self, *keys: str) -> None:
        self._grants_box[:] = list(keys)

    def _post(self) -> httpx.Response:
        return self._app().post(
            f"/api/v1/ai/crm/activities/{uuid.uuid4()}/transcript",
            json={"transcript": "customer asked about pricing"},
        )

    def test_post_with_invoke_and_crm_write(self) -> None:
        self._grant(ERP_AI_INVOKE, ERP_CRM_WRITE)
        assert self._post().status_code == 200

    def test_post_without_crm_write_denied(self) -> None:
        self._grant(ERP_AI_INVOKE)
        assert self._post().status_code == 403

    def test_post_without_invoke_denied(self) -> None:
        self._grant(ERP_CRM_WRITE)
        assert self._post().status_code == 403


class TestCrmAnomalyForwarding:
    def test_list_forwards(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.get(
            "/api/v1/ai/crm/anomalies",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert seen[0].url.path == "/api/v1/ai/crm/anomalies"

    def test_resolve_post_forwards_uuid(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)
        anomaly_id = uuid.uuid4()

        response = client.post(
            f"/api/v1/ai/crm/anomalies/{anomaly_id}/resolve",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert seen[0].url.path == f"/api/v1/ai/crm/anomalies/{anomaly_id}/resolve"

    def test_dismiss_post_forwards_uuid(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)
        anomaly_id = uuid.uuid4()

        response = client.post(
            f"/api/v1/ai/crm/anomalies/{anomaly_id}/dismiss",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert seen[0].url.path == f"/api/v1/ai/crm/anomalies/{anomaly_id}/dismiss"

    @pytest.mark.parametrize(
        ("suffix", "bad_id"),
        [
            pytest.param("/resolve", "not-a-uuid", id="garbage"),
            pytest.param("/dismiss", "x@evil.test", id="authority-like"),
        ],
    )
    def test_malformed_id_rejected_before_any_forward(self, suffix: str, bad_id: str) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.post(f"/api/v1/ai/crm/anomalies/{bad_id}{suffix}")

        assert response.status_code == 422
        assert seen == [], "malformed id must never reach ai-agent"


class TestCrmAnomalyPermissionGate:
    """List is read-like (invoke + crm read); resolve/dismiss are write-like
    (invoke + crm write)."""

    @pytest.fixture(autouse=True)
    def _patch_rbac(self, monkeypatch: pytest.MonkeyPatch) -> None:
        grants: list[str] = []
        self._grants_box = grants

        class _FakeRbac:
            def __init__(self, session: object) -> None:
                self.session = session

            async def resolve_user_permissions(
                self, *, user_id: object, tenant_id: object
            ) -> list[str]:
                return grants

        monkeypatch.setattr(api_deps, "RbacRepository", _FakeRbac)

    def _app(self) -> TestClient:
        app = FastAPI()
        app.add_exception_handler(SkyrictError, skyrict_error_handler)
        app.include_router(ai_router.router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": str(uuid.uuid4()),
            "tenant_id": str(uuid.uuid4()),
        }
        app.dependency_overrides[get_db] = lambda: object()
        app.dependency_overrides[get_current_scope] = lambda: (DataScope.ALL, None)
        app.dependency_overrides[ai_router.get_ai_client] = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True})),
            base_url="http://ai.test",
        )
        return TestClient(app)

    def _grant(self, *keys: str) -> None:
        self._grants_box[:] = list(keys)

    def _list(self) -> httpx.Response:
        return self._app().get("/api/v1/ai/crm/anomalies")

    def _resolve(self) -> httpx.Response:
        return self._app().post(f"/api/v1/ai/crm/anomalies/{uuid.uuid4()}/resolve")

    def _dismiss(self) -> httpx.Response:
        return self._app().post(f"/api/v1/ai/crm/anomalies/{uuid.uuid4()}/dismiss")

    def test_list_requires_invoke_and_crm_read(self) -> None:
        self._grant(ERP_AI_INVOKE, ERP_CRM_READ)
        assert self._list().status_code == 200

    def test_list_without_crm_read_denied(self) -> None:
        self._grant(ERP_AI_INVOKE)
        assert self._list().status_code == 403

    def test_list_without_invoke_denied(self) -> None:
        self._grant(ERP_CRM_READ)
        assert self._list().status_code == 403

    def test_resolve_requires_invoke_and_crm_write(self) -> None:
        self._grant(ERP_AI_INVOKE, ERP_CRM_WRITE)
        assert self._resolve().status_code == 200

    def test_resolve_without_crm_write_denied(self) -> None:
        self._grant(ERP_AI_INVOKE)
        assert self._resolve().status_code == 403

    def test_resolve_without_invoke_denied(self) -> None:
        self._grant(ERP_CRM_WRITE)
        assert self._resolve().status_code == 403

    def test_dismiss_requires_invoke_and_crm_write(self) -> None:
        self._grant(ERP_AI_INVOKE, ERP_CRM_WRITE)
        assert self._dismiss().status_code == 200


class TestDashboardSuggestForwarding:
    """BUG-AI-002 proxy: POST /ai/dashboards/suggest must reach ai-agent unchanged."""

    def test_suggest_forwards_path_and_body(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.post(
            "/api/v1/ai/dashboards/suggest",
            json={"current_layout": [{"id": "ai_digest", "order": 0, "cols": 4, "visible": True}]},
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert len(seen) == 1
        assert seen[0].url.path == "/api/v1/ai/dashboards/suggest"
        assert (
            seen[0].read()
            == b'{"current_layout":[{"id":"ai_digest","order":0,"cols":4,"visible":true}]}'
        )


class TestDashboardSuggestPermissionGate:
    """Suggest is a pure AI invoke: erp.ai.invoke is the only gate."""

    @pytest.fixture(autouse=True)
    def _patch_rbac(self, monkeypatch: pytest.MonkeyPatch) -> None:
        grants: list[str] = []
        self._grants_box = grants

        class _FakeRbac:
            def __init__(self, session: object) -> None:
                self.session = session

            async def resolve_user_permissions(
                self, *, user_id: object, tenant_id: object
            ) -> list[str]:
                return grants

        monkeypatch.setattr(api_deps, "RbacRepository", _FakeRbac)

    def _app(self) -> TestClient:
        app = FastAPI()
        app.add_exception_handler(SkyrictError, skyrict_error_handler)
        app.include_router(ai_router.router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
        }
        app.dependency_overrides[get_db] = lambda: object()
        app.dependency_overrides[ai_router.get_ai_client] = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True})),
            base_url="http://ai.test",
        )
        return TestClient(app)

    def _grant(self, *keys: str) -> None:
        self._grants_box[:] = list(keys)

    def _suggest(self) -> httpx.Response:
        return self._app().post("/api/v1/ai/dashboards/suggest")

    def test_suggest_with_invoke(self) -> None:
        self._grant(ERP_AI_INVOKE)
        assert self._suggest().status_code == 200

    def test_suggest_without_invoke_denied(self) -> None:
        self._grant()
        assert self._suggest().status_code == 403
