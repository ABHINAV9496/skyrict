"""Reporting data layer integration - REAL Postgres (RPT-DATA-001, M-RPT §§Rules/AC).

Proves the tenant data layer end-to-end against the migrated schema:

  - the provisioning hook (``core.seed.seed_reporting_defaults``) applies the
    SAME canonical Phase-1 pack migration 0036 seeds pre-existing tenants with;
  - every seed SQL actually compiles/runs against the real schema (catches any
    column-name drift the unit-level validator cannot);
  - snapshot refresh is idempotent per (definition, period) - the §M-RPT AC;
  - the composite-FK convention rejects cross-tenant snapshots even as owner;
  - RLS (``tenant_isolation_erp_report_*``) isolates the two report tables:
    tenant B cannot read tenant A's definitions via a non-owner role.

Like ``test_rls.py``: the dev ``skyrict`` superuser bypasses RLS, so the
isolation tests ``SET ROLE`` to the ``core_rls_smoke`` test role (created in a
module-scoped setup; skipped when the local role cannot CREATEROLE).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from core.db.session import async_session_factory, engine
from core.features.reporting.models.report_definition import ErpReportDefinitionModel
from core.features.reporting.models.report_snapshot import ErpReportSnapshotModel
from core.features.reporting.repository import ReportRepository
from core.features.reporting.seeds import PHASE_1_REPORT_SEEDS
from core.models.tenant import TenantModel
from core.seed import seed_reporting_defaults

pytestmark = pytest.mark.integration

RLS_ROLE = "core_rls_smoke"

_REPORT_TABLES = ("erp_report_definitions", "erp_report_snapshots")


@pytest.fixture(scope="module")
def reporting_world(migrated_schema: None) -> dict[str, str]:
    """Two tenants, each seeded with the Phase-1 report pack; return ids.

    Plain (sync) fixture: all DB work runs inside one ``asyncio.run()`` and the
    engine pool is disposed before that run's loop closes, so the function-
    scoped async tests that follow get a clean pool bound to their own loops.
    """

    async def _setup() -> dict[str, str]:
        tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
        async with async_session_factory() as session:
            session.add_all(
                [
                    TenantModel(
                        id=uuid.UUID(tenant_a),
                        name="Reporting Tenant A",
                        slug=f"rpt-a-{tenant_a[:8]}",
                        plan_tier="free",
                        is_active=True,
                    ),
                    TenantModel(
                        id=uuid.UUID(tenant_b),
                        name="Reporting Tenant B",
                        slug=f"rpt-b-{tenant_b[:8]}",
                        plan_tier="free",
                        is_active=True,
                    ),
                ]
            )
            await session.commit()

        await seed_reporting_defaults(uuid.UUID(tenant_a))
        await seed_reporting_defaults(uuid.UUID(tenant_b))

        async with async_session_factory() as session:
            defs = (
                (
                    await session.execute(
                        select(ErpReportDefinitionModel).where(
                            ErpReportDefinitionModel.tenant_id == uuid.UUID(tenant_a)
                        )
                    )
                )
                .scalars()
                .all()
            )
            await engine.dispose()
        return {
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "definition_a": str(defs[0].id),
            "slug_a": defs[0].slug,
        }

    async def _teardown() -> None:
        async with async_session_factory() as session:
            for tid in (reporting_world_data["tenant_a"], reporting_world_data["tenant_b"]):
                await session.execute(
                    text("DELETE FROM tenants WHERE id = :tid"), {"tid": uuid.UUID(tid)}
                )
            await session.commit()
            await engine.dispose()

    reporting_world_data = asyncio.run(_setup())
    try:
        yield reporting_world_data
    finally:
        asyncio.run(_teardown())


async def _ensure_rls_role() -> None:
    """Create/refresh the non-owner RLS test role with report-table privileges."""
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{RLS_ROLE}') "
                f"THEN CREATE ROLE {RLS_ROLE} NOLOGIN; "
                "END IF; END $$;"
            )
            await conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {RLS_ROLE}")
            for table in _REPORT_TABLES:
                await conn.exec_driver_sql(
                    f"GRANT SELECT, INSERT ON TABLE public.{table} TO {RLS_ROLE}"
                )
    except ProgrammingError as exc:
        if "permission denied to create role" not in str(exc).lower():
            raise
        pytest.skip(
            "SQL-level RLS smoke tests require a role with CREATEROLE to create "
            "the non-owner 'core_rls_smoke' test role. Run against the compose/"
            'CI stack, or: psql -U postgres -c "ALTER ROLE skyrict CREATEROLE"'
        )


class TestProvisioningHook:
    async def test_seeds_full_pack_per_tenant(self, reporting_world: dict[str, str]) -> None:
        async with async_session_factory() as session:
            for tid_key in ("tenant_a", "tenant_b"):
                count = (
                    await session.execute(
                        select(func.count())
                        .select_from(ErpReportDefinitionModel)
                        .where(
                            ErpReportDefinitionModel.tenant_id
                            == uuid.UUID(reporting_world[tid_key])
                        )
                    )
                ).scalar_one()
                assert count == len(PHASE_1_REPORT_SEEDS), tid_key

            # Every definition is gated by the catalogue permission.
            bad_keys = (
                (
                    await session.execute(
                        text(
                            "SELECT DISTINCT permission_key FROM erp_report_definitions "
                            "WHERE permission_key <> 'erp.reports.read'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert bad_keys == []

    async def test_provisioning_hook_idempotent(self, reporting_world: dict[str, str]) -> None:
        await seed_reporting_defaults(uuid.UUID(reporting_world["tenant_a"]))

        async with async_session_factory() as session:
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(ErpReportDefinitionModel)
                    .where(
                        ErpReportDefinitionModel.tenant_id == uuid.UUID(reporting_world["tenant_a"])
                    )
                )
            ).scalar_one()
            assert count == len(PHASE_1_REPORT_SEEDS)


class TestSeedSqlsAgainstRealSchema:
    @pytest.mark.asyncio
    async def test_every_seed_sql_runs_against_migrated_schema(
        self, reporting_world: dict[str, str]
    ) -> None:
        """Execute all 12 dataset queries with real params - proves the SQL
        matches the migrated column names (unit validator cannot)."""
        fixture_params: dict[str, Any] = {
            "tenant_id": uuid.UUID(reporting_world["tenant_a"]),
            "from_date": date(2026, 1, 1),
            "to_date": date(2026, 12, 31),
            "as_of_date": date(2026, 12, 31),
        }
        async with engine.connect() as conn:
            for seed in PHASE_1_REPORT_SEEDS:
                params = {name: fixture_params[name] for name in seed.params}
                result = await conn.execute(text(seed.sql), params)
                result.fetchall()  # drain the cursor; empty results are fine


class TestSnapshotContract:
    @pytest.mark.asyncio
    async def test_snapshot_round_trip_via_repository(
        self, reporting_world: dict[str, str]
    ) -> None:
        tenant_id = uuid.UUID(reporting_world["tenant_a"])
        definition_id = uuid.UUID(reporting_world["definition_a"])
        period = date(2026, 9, 1)
        payload = [
            {"account": "revenue", "total": "123.4500"},
            {"account": "expense", "total": "-9.0000"},
        ]

        async with async_session_factory() as session:
            repo = ReportRepository(session)
            stored = await repo.upsert_snapshot(
                tenant_id=tenant_id,
                definition_id=definition_id,
                period=period,
                payload=payload,
            )
            await session.commit()

            fetched = await repo.get_snapshot(
                tenant_id=tenant_id,
                definition_id=definition_id,
                period=period,
            )
        assert fetched is not None
        assert fetched.id == stored.id
        assert fetched.payload == payload  # byte-identical JSONB round-trip

    @pytest.mark.asyncio
    async def test_snapshot_refresh_is_idempotent_per_period(
        self, reporting_world: dict[str, str]
    ) -> None:
        tenant_id = uuid.UUID(reporting_world["tenant_a"])
        definition_id = uuid.UUID(reporting_world["definition_a"])
        period = date(2026, 9, 2)

        async with async_session_factory() as session:
            repo = ReportRepository(session)
            first = await repo.upsert_snapshot(
                tenant_id=tenant_id,
                definition_id=definition_id,
                period=period,
                payload=[{"old": True}],
            )
            refreshed = await repo.upsert_snapshot(
                tenant_id=tenant_id,
                definition_id=definition_id,
                period=period,
                payload=[{"new": True}],
            )
            await session.commit()

            rows = (
                (
                    await session.execute(
                        select(ErpReportSnapshotModel).where(
                            ErpReportSnapshotModel.tenant_id == tenant_id,
                            ErpReportSnapshotModel.definition_id == definition_id,
                            ErpReportSnapshotModel.period == period,
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 1, "refresh must replace, never duplicate - §M-RPT AC"
        assert first.id == refreshed.id
        assert rows[0].payload == [{"new": True}]

    @pytest.mark.asyncio
    async def test_cross_tenant_snapshot_rejected_by_composite_fk(
        self, reporting_world: dict[str, str]
    ) -> None:
        """The composite FK (tenant_b, definition_a) cannot exist - definition_a
        belongs to tenant A - so a misplaced write fails even as the owner."""
        tenant_b = uuid.UUID(reporting_world["tenant_b"])
        definition_a = uuid.UUID(reporting_world["definition_a"])

        async with async_session_factory() as session:
            with pytest.raises(IntegrityError) as excinfo:
                await session.execute(
                    text(
                        "INSERT INTO erp_report_snapshots "
                        "(tenant_id, id, definition_id, period, payload) "
                        "VALUES (:tid, gen_random_uuid(), :def, '2026-09-01', '[]'::jsonb)"
                    ),
                    {"tid": tenant_b, "def": definition_a},
                )
            assert "fk_erp_report_snapshots_definition" in str(excinfo.value)
            await session.rollback()


class TestReportRls:
    @pytest.mark.asyncio
    async def test_tenant_b_cannot_read_tenant_a_definitions(
        self, reporting_world: dict[str, str]
    ) -> None:
        await _ensure_rls_role()

        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET ROLE {RLS_ROLE}")
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (reporting_world["tenant_a"],),
            )
            a_rows = (
                (await conn.execute(text("SELECT id FROM erp_report_definitions"))).scalars().all()
            )
            assert len(a_rows) == len(PHASE_1_REPORT_SEEDS)

            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (reporting_world["tenant_b"],),
            )
            b_ids = [
                str(row)
                for row in (await conn.execute(text("SELECT id FROM erp_report_definitions")))
                .scalars()
                .all()
            ]
            assert len(b_ids) == len(PHASE_1_REPORT_SEEDS)
            assert reporting_world["definition_a"] not in b_ids  # tenant B cannot read A's rows

            await conn.exec_driver_sql("RESET ROLE")
        await engine.dispose()
