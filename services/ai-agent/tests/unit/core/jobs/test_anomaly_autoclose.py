"""Unit tests for the per-tenant anomaly auto-close job.

Exercises ``close_all_tenants`` orchestration with fakes for the session
factory and a stub repository that records the pinned ``TenantContext`` at
call time; the repository UPDATE path is covered by the anomaly repository
tests.
"""

from __future__ import annotations

import uuid

from ai_agent.core.jobs.anomaly_autoclose import close_all_tenants
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
    def __init__(self, rows: list[TenantModel]) -> None:
        self._rows = rows
        self.commits = 0

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def execute(self, stmt: object) -> _FakeResult:
        return _FakeResult(self._rows)

    async def commit(self) -> None:
        self.commits += 1


def _session_factory(rows: list[TenantModel]) -> object:
    def factory() -> _FakeSession:
        return _FakeSession(rows)

    return factory


def _tenant(slug: str, tenant_id: uuid.UUID) -> TenantModel:
    return TenantModel(id=tenant_id, name=slug.title(), slug=slug, plan_tier="free", is_active=True)


def _stub_repo_factory(record: dict, *, fail_tenant: uuid.UUID | None = None) -> object:
    def factory(session: object) -> object:
        class _Repo:
            async def auto_close_stale(self, **kwargs: object) -> int:
                assert isinstance(session, _FakeSession)
                record["commits"].append(session.commits)
                record["ctx"].append(TenantContext.get())
                record["slug"].append(TenantContext.get_tenant_slug())
                record["close_days"].append(kwargs["close_days"])
                if TenantContext.get() == str(fail_tenant):
                    raise RuntimeError("database unreachable")
                return 1

        return _Repo()

    return factory


class TestCloseAllTenants:
    async def test_skips_when_no_active_tenants(self) -> None:
        record: dict = {"ctx": [], "slug": [], "close_days": [], "commits": []}
        total = await close_all_tenants(
            session_factory=_session_factory([]),  # type: ignore[arg-type]
            repo_factory=_stub_repo_factory(record),  # type: ignore[arg-type]
        )
        assert total == 0
        assert record["ctx"] == []

    async def test_autocloses_each_tenant_with_pinned_context(self) -> None:
        record: dict = {"ctx": [], "slug": [], "close_days": [], "commits": []}
        tenants = [_tenant("acme", TENANT_A), _tenant("globex", TENANT_B)]
        total = await close_all_tenants(
            session_factory=_session_factory(tenants),  # type: ignore[arg-type]
            repo_factory=_stub_repo_factory(record),  # type: ignore[arg-type]
        )
        assert total == 2
        assert record["ctx"] == [str(TENANT_A), str(TENANT_B)]
        assert record["slug"] == ["acme", "globex"]
        # Each pass ran in its own session and committed before the next.
        assert record["commits"] == [0, 0]

    async def test_isolates_per_tenant_failures(self) -> None:
        record: dict = {"ctx": [], "slug": [], "close_days": [], "commits": []}
        tenants = [_tenant("acme", TENANT_A), _tenant("globex", TENANT_B)]
        total = await close_all_tenants(
            session_factory=_session_factory(tenants),  # type: ignore[arg-type]
            repo_factory=_stub_repo_factory(record, fail_tenant=TENANT_A),  # type: ignore[arg-type]
        )
        # TENANT_A raised; the pass must continue to TENANT_B.
        assert total == 1
        assert record["ctx"] == [str(TENANT_A), str(TENANT_B)]
