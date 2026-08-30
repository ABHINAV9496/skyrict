"""Unit tests for the scheduled per-tenant anomaly scan (spec §4.3).

Exercises the orchestration with fakes for the session factory and service
factory; the real repository + gateway paths are covered by the integration
migration round-trip and the gateway tests respectively.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from ai_agent.api.scheduled.anomaly_scan import scan_all_tenants
from ai_agent.core.tenant_context import TenantContext
from ai_agent.models.tenant import TenantModel

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


class _FakeScalars:
    def __init__(self, rows: list[TenantModel]) -> None:
        self._rows = rows

    def all(self) -> list[TenantModel]:
        return self._rows


class _FakeResult:
    def __init__(self, rows: list[TenantModel]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeSession:
    def __init__(self, rows: list[TenantModel], commits: list[str]) -> None:
        self._rows = rows
        self._commits = commits

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def execute(self, stmt: object) -> _FakeResult:
        return _FakeResult(self._rows)

    async def commit(self) -> None:
        self._commits.append("commit")


def _session_factory(rows: list[TenantModel], commits: list[str]) -> object:
    def factory() -> _FakeSession:
        return _FakeSession(rows, commits)

    return factory


def _tenant(slug: str, tenant_id: uuid.UUID) -> TenantModel:
    return TenantModel(id=tenant_id, name=slug.title(), slug=slug, plan_tier="free", is_active=True)


class _FakeScanService:
    def __init__(self, record: dict) -> None:
        self._record = record

    async def run_scan(self, *, tenant_id: uuid.UUID):
        self._record["scanned"].append(tenant_id)
        return SimpleNamespace(detected=1, duplicates_skipped=0)


class TestScanAllTenants:
    async def test_skipped_without_service_token(self) -> None:
        called = False

        def factory():
            nonlocal called
            called = True
            return _FakeSession([], [])

        await scan_all_tenants(
            service_token="",
            base_url="http://core:8000",
            session_factory=factory,  # type: ignore[arg-type]
        )
        assert called is False, "no session must be opened without a token"

    async def test_skips_when_no_active_tenants(self) -> None:
        commits: list[str] = []

        def exploding_service(session, gateway):
            raise AssertionError("service must not be built without tenants")

        await scan_all_tenants(
            service_token="tok",
            base_url="http://core:8000",
            session_factory=_session_factory([], commits),  # type: ignore[arg-type]
            service_factory=exploding_service,  # type: ignore[arg-type]
        )
        assert commits == []

    async def test_scans_each_active_tenant_with_context_and_gateway_headers(
        self,
    ) -> None:
        commits: list[str] = []
        record: dict = {"scanned": [], "ctx": [], "slug": [], "gateways": []}

        def fake_service(session, gateway):
            record["ctx"].append(TenantContext.get())
            record["slug"].append(TenantContext.get_tenant_slug())
            record["gateways"].append(gateway)
            return _FakeScanService(record)

        tenants = [_tenant("acme", TENANT_A), _tenant("globex", TENANT_B)]
        await scan_all_tenants(
            service_token="svc-tok",
            base_url="http://core:8000",
            session_factory=_session_factory(tenants, commits),  # type: ignore[arg-type]
            service_factory=fake_service,  # type: ignore[arg-type]
        )

        assert record["scanned"] == [TENANT_A, TENANT_B]
        assert record["ctx"] == [str(TENANT_A), str(TENANT_B)]
        assert record["slug"] == ["acme", "globex"]
        assert [gateway._headers()["X-Tenant-Slug"] for gateway in record["gateways"]] == [
            "acme",
            "globex",
        ]
        assert all(
            gateway._headers()["Authorization"] == "Bearer svc-tok"
            for gateway in record["gateways"]
        )
        assert commits == ["commit", "commit"]

    async def test_single_tenant_failure_is_isolated(self) -> None:
        commits: list[str] = []
        record: dict = {"scanned": [], "calls": 0}

        def flaky_service(session, gateway):
            record["calls"] += 1
            if record["calls"] == 1:

                class _BoomScanService:
                    async def run_scan(self, *, tenant_id: uuid.UUID):
                        raise RuntimeError("core unreachable")

                return _BoomScanService()
            return _FakeScanService(record)

        tenants = [_tenant("acme", TENANT_A), _tenant("globex", TENANT_B)]
        await scan_all_tenants(
            service_token="tok",
            base_url="http://core:8000",
            session_factory=_session_factory(tenants, commits),  # type: ignore[arg-type]
            service_factory=flaky_service,  # type: ignore[arg-type]
        )

        assert record["calls"] == 2
        assert record["scanned"] == [TENANT_B], "pass must continue past failures"
        assert commits == ["commit"]
