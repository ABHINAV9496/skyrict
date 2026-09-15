"""ReportCacheRepository integration - REAL Postgres (SKY-99).

Proves the write-through aggregate cache contract end-to-end:
  - put/get round-trip through the ORM repository with the tenant GUC pinned
    (the exact production path: TenantContext -> after_begin -> set_config);
  - a same-key repeat upserts and increments hit_count (ON CONFLICT DO
    UPDATE on the unique index, not a constraint);
  - zero/negative-TTL entries are invisible to get and purged by
    delete_expired / sweep_expired_report_cache;
  - the erp_report_cache table honors tenant RLS: a non-owner role scoped to
    tenant B can neither read tenant A's cached rows nor insert a row for
    tenant B while scoped to tenant A (WITH CHECK).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError

from core.core.tenant_context import TenantContext
from core.db.session import async_session_factory, engine
from core.features.finance.models.erp_report_cache import ErpReportCacheModel
from core.features.finance.report_cache import REPORT_CACHE_TTL_SECONDS, ReportCacheRepository
from core.features.finance.report_cache_sweep import sweep_expired_report_cache
from core.models.tenant import TenantModel

pytestmark = pytest.mark.integration

RLS_ROLE = "core_rls_smoke"


@pytest.fixture(scope="module")
def cache_world(migrated_schema: None) -> dict[str, str]:
    """Two tenants available for cache reads/writes."""

    async def _setup() -> dict[str, str]:
        tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
        async with async_session_factory() as session:
            session.add_all(
                [
                    TenantModel(
                        id=uuid.UUID(tenant_a),
                        name="Cache Tenant A",
                        slug=f"cch-a-{tenant_a[:8]}",
                        plan_tier="free",
                        is_active=True,
                    ),
                    TenantModel(
                        id=uuid.UUID(tenant_b),
                        name="Cache Tenant B",
                        slug=f"cch-b-{tenant_b[:8]}",
                        plan_tier="free",
                        is_active=True,
                    ),
                ]
            )
            await session.commit()
        await engine.dispose()
        return {"tenant_a": tenant_a, "tenant_b": tenant_b}

    async def _teardown() -> None:
        async with async_session_factory() as session:
            for tid in (cache_world["tenant_a"], cache_world["tenant_b"]):
                await session.execute(
                    text("DELETE FROM tenants WHERE id = :tid"), {"tid": uuid.UUID(tid)}
                )
            await session.commit()
            await engine.dispose()

    cache_world = asyncio.run(_setup())
    try:
        yield cache_world
    finally:
        asyncio.run(_teardown())


@pytest.fixture(autouse=True)
async def clean_cache(cache_world: dict[str, str]) -> None:
    """Give every test a clean slate; each test owns its cache keys."""
    TenantContext.reset()
    async with async_session_factory() as session:
        await session.execute(
            text("DELETE FROM erp_report_cache WHERE tenant_id IN (:a, :b)"),
            {"a": uuid.UUID(cache_world["tenant_a"]), "b": uuid.UUID(cache_world["tenant_b"])},
        )
        await session.commit()
    yield
    TenantContext.reset()


def _pin_tenant(tenant_id: str) -> None:
    TenantContext.reset()
    TenantContext.set(tenant_id)


async def _row_count(tenant_id: uuid.UUID) -> int:
    async with async_session_factory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(ErpReportCacheModel)
            .where(ErpReportCacheModel.tenant_id == tenant_id)
        )
        return result.scalar_one()


async def _ensure_cache_rls_role() -> None:
    """Grant the shared non-owner RLS role access to the cache table."""
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{RLS_ROLE}') "
                f"THEN CREATE ROLE {RLS_ROLE} NOLOGIN; "
                "END IF; END $$;"
            )
            await conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {RLS_ROLE}")
            await conn.exec_driver_sql(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.erp_report_cache "
                f"TO {RLS_ROLE}"
            )
    except ProgrammingError as exc:
        if "permission denied to create role" not in str(exc).lower():
            raise
        pytest.skip(
            "SQL-level RLS tests require a CREATEROLE-capable skyrict (compose/CI "
            "image is a superuser). See test_rls.py for the exact grant."
        )


class TestCacheRoundTrip:
    async def test_put_then_get_returns_payload(self, cache_world: dict[str, str]) -> None:
        _pin_tenant(cache_world["tenant_a"])
        try:
            tenant_id = uuid.UUID(cache_world["tenant_a"])
            key = "cashflow_projection|2026-01-01"
            payload = {"months": [{"net": "105.00"}]}
            async with async_session_factory() as session:
                repo = ReportCacheRepository(session)
                await repo.put(tenant_id=tenant_id, cache_key=key, payload=payload)
                await session.commit()
                found = await repo.get(tenant_id=tenant_id, cache_key=key)
            assert found is not None
            assert found["months"][0]["net"] == "105.00"
        finally:
            TenantContext.reset()

    async def test_same_key_upserts_and_increments_hit_count(
        self, cache_world: dict[str, str]
    ) -> None:
        _pin_tenant(cache_world["tenant_a"])
        try:
            tenant_id = uuid.UUID(cache_world["tenant_a"])
            key = "cashflow_projection|2026-01-01"
            async with async_session_factory() as session:
                repo = ReportCacheRepository(session)
                await repo.put(tenant_id=tenant_id, cache_key=key, payload={"v": "1"})
                await repo.put(tenant_id=tenant_id, cache_key=key, payload={"v": "2"})
                await session.commit()
            async with async_session_factory() as session:
                result = await session.execute(
                    select(ErpReportCacheModel).where(
                        ErpReportCacheModel.tenant_id == tenant_id,
                        ErpReportCacheModel.cache_key == key,
                    )
                )
                row = result.scalar_one()
            assert row.payload == {"v": "2"}  # upsert overwrote payload
            assert row.hit_count == 1  # second put bumped the counter
            assert await _row_count(tenant_id) == 1  # no duplicate rows
        finally:
            TenantContext.reset()

    async def test_expired_entry_is_invisible_to_get(self, cache_world: dict[str, str]) -> None:
        _pin_tenant(cache_world["tenant_a"])
        try:
            tenant_id = uuid.UUID(cache_world["tenant_a"])
            key = "stale|report"
            async with async_session_factory() as session:
                repo = ReportCacheRepository(session)
                await repo.put(
                    tenant_id=tenant_id, cache_key=key, payload={"v": "x"}, ttl_seconds=0
                )
                await session.commit()
                found = await repo.get(tenant_id=tenant_id, cache_key=key)
            assert found is None
        finally:
            TenantContext.reset()

    async def test_delete_expired_purges_only_expired(self, cache_world: dict[str, str]) -> None:
        _pin_tenant(cache_world["tenant_a"])
        try:
            tenant_id = uuid.UUID(cache_world["tenant_a"])
            async with async_session_factory() as session:
                repo = ReportCacheRepository(session)
                await repo.put(tenant_id=tenant_id, cache_key="keep", payload={"v": "live"})
                await repo.put(
                    tenant_id=tenant_id, cache_key="drop", payload={"v": "stale"}, ttl_seconds=0
                )
                await session.commit()
                deleted = await repo.delete_expired()
                await session.commit()
            assert deleted == 1
            assert await _row_count(tenant_id) == 1
        finally:
            TenantContext.reset()

    async def test_sweep_pins_tenant_and_removes_expired(self, cache_world: dict[str, str]) -> None:
        _pin_tenant(cache_world["tenant_a"])
        try:
            tenant_id = uuid.UUID(cache_world["tenant_a"])
            async with async_session_factory() as session:
                repo = ReportCacheRepository(session)
                await repo.put(
                    tenant_id=tenant_id, cache_key="sweep-me", payload={"v": "x"}, ttl_seconds=0
                )
                await repo.put(tenant_id=tenant_id, cache_key="sweep-keep", payload={"v": "y"})
                await session.commit()
            deleted = await sweep_expired_report_cache()
            assert deleted >= 1
            assert await _row_count(tenant_id) == 1
        finally:
            TenantContext.reset()


class TestCacheRls:
    async def test_tenant_b_cannot_read_or_write_tenant_a_cache(
        self, cache_world: dict[str, str]
    ) -> None:
        await _ensure_cache_rls_role()

        _pin_tenant(cache_world["tenant_a"])
        try:
            tenant_a = uuid.UUID(cache_world["tenant_a"])
            key = "cashflow_projection|2026-01-01"
            async with async_session_factory() as session:
                repo = ReportCacheRepository(session)
                await repo.put(tenant_id=tenant_a, cache_key=key, payload={"v": "a"})
                await session.commit()
        finally:
            TenantContext.reset()

        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET ROLE {RLS_ROLE}")
            # tenant B scoped: tenant A's row is invisible
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (cache_world["tenant_b"],),
            )
            visible = (
                (
                    await conn.execute(
                        select(ErpReportCacheModel.cache_key).where(
                            ErpReportCacheModel.tenant_id == tenant_a
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert key not in visible

            # tenant A scoped but inserting a tenant B row violates WITH CHECK
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (cache_world["tenant_a"],),
            )
            with pytest.raises(ProgrammingError) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_report_cache "
                        "(tenant_id, id, cache_key, payload, expires_at) "
                        "VALUES (:tid, gen_random_uuid(), 'x|y', "
                        "jsonb_build_object('v', 1), now() + interval '300 seconds')"
                    ),
                    {"tid": uuid.UUID(cache_world["tenant_b"])},
                )
            assert "row-level security" in str(excinfo.value).lower()
            await conn.rollback()
            await conn.exec_driver_sql("RESET ROLE")

        await engine.dispose()


class TestCacheTtlConstant:
    def test_ttl_is_five_minutes(self) -> None:
        assert REPORT_CACHE_TTL_SECONDS == 300
        now = datetime.now(UTC)
        assert now + timedelta(seconds=REPORT_CACHE_TTL_SECONDS) - now == timedelta(seconds=300)
