"""SQL-level Row-Level Security smoke tests — verified against REAL Postgres.

These tests prove the RLS security boundary at the database layer, not through
mocks or the HTTP stack:

  - ``current_tenant_id()`` exists after ``alembic upgrade head``;
  - the GUC ``app.current_tenant_id`` (set by db/session.py's ``after_begin``)
    drives the policy function;
  - a NON-OWNER role (the ``core_rls_smoke`` test role) sees only its tenant's
    rows — tenant B cannot read tenant A rows;
  - cross-tenant INSERTs are rejected by the RLS ``WITH CHECK``;
  - the composite-FK convention rejects a cross-tenant role grant even as the
    table OWNER (referential integrity agrees with RLS).

The dev ``skyrict`` user owns the tables (and is a superuser in the compose
stack), so RLS is bypassed for it — exactly as in production where the app
connects as a non-owner role. ``SET ROLE`` to the smoke role simulates that.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from core.db.session import async_session_factory, engine
from core.models.core_role import CoreRoleModel
from core.models.core_user_role import CoreUserRoleModel
from core.models.tenant import TenantModel

pytestmark = pytest.mark.integration

RLS_ROLE = "core_rls_smoke"


@pytest.fixture(scope="module")
def rls_world(migrated_schema: None) -> dict[str, str]:
    """Seed two tenants with one role each + one grant; return their ids.

    Plain (sync) fixture: all DB work runs inside one ``asyncio.run()`` and the
    engine pool is disposed before that run's loop closes, so the function-
    scoped async tests that follow get a clean pool bound to their own loops.
    """

    async def _setup() -> dict[str, str]:
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        role_a = str(uuid.uuid4())
        role_b = str(uuid.uuid4())

        async with async_session_factory() as session:
            session.add_all(
                [
                    TenantModel(
                        id=uuid.UUID(tenant_a),
                        name="Tenant A",
                        slug=f"rls-a-{tenant_a[:8]}",
                        plan_tier="free",
                        is_active=True,
                    ),
                    TenantModel(
                        id=uuid.UUID(tenant_b),
                        name="Tenant B",
                        slug=f"rls-b-{tenant_b[:8]}",
                        plan_tier="free",
                        is_active=True,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    CoreRoleModel(
                        tenant_id=uuid.UUID(tenant_a),
                        id=uuid.UUID(role_a),
                        name="owner",
                        permissions=["*"],
                    ),
                    CoreRoleModel(
                        tenant_id=uuid.UUID(tenant_b),
                        id=uuid.UUID(role_b),
                        name="viewer",
                        permissions=["erp.inventory.read"],
                    ),
                ]
            )
            await session.flush()
            session.add(
                CoreUserRoleModel(
                    tenant_id=uuid.UUID(tenant_a),
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(user_id),
                    role_id=uuid.UUID(role_a),
                )
            )
            await session.commit()
            await engine.dispose()

        return {
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "role_a": role_a,
            "role_b": role_b,
            "user_id": user_id,
        }

    async def _teardown() -> None:
        # Own rows only (owner role bypasses RLS for DELETE too).
        async with async_session_factory() as session:
            for table in (CoreUserRoleModel, CoreRoleModel):
                await session.execute(
                    text(f"DELETE FROM {table.__tablename__} WHERE tenant_id = :tid"),
                    {"tid": uuid.UUID(rls_world_data["tenant_a"])},
                )
            await session.execute(
                text("DELETE FROM core_roles WHERE tenant_id = :tid"),
                {"tid": uuid.UUID(rls_world_data["tenant_b"])},
            )
            for tid in (rls_world_data["tenant_a"], rls_world_data["tenant_b"]):
                await session.execute(
                    text("DELETE FROM tenants WHERE id = :tid"), {"tid": uuid.UUID(tid)}
                )
            await session.commit()
            await engine.dispose()

    rls_world_data = asyncio.run(_setup())
    try:
        yield rls_world_data
    finally:
        asyncio.run(_teardown())


async def _ensure_rls_role() -> None:
    """Create the non-owner RLS test role (superuser required; dev stack: yes).

    The dev ``skyrict`` user owns the core tables and bypasses RLS, so the
    smoke tests need a NON-OWNER role to prove the policies bite. The compose
    stack's ``skyrict`` is a superuser (the official postgres image makes
    ``POSTGRES_USER`` a superuser) and can create the role; when the local
    database has a non-superuser ``skyrict`` without ``CREATEROLE`` the tests
    skip with this actionable message instead of failing.
    """
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{RLS_ROLE}') "
                f"THEN CREATE ROLE {RLS_ROLE} NOLOGIN; "
                "END IF; END $$;"
            )
            await conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {RLS_ROLE}")
            for table in ("core_roles", "core_user_roles"):
                await conn.exec_driver_sql(
                    f"GRANT SELECT, INSERT ON TABLE public.{table} TO {RLS_ROLE}"
                )
            for table in ("erp_currencies", "core_permissions", "tenants"):
                await conn.exec_driver_sql(f"GRANT SELECT ON TABLE public.{table} TO {RLS_ROLE}")
    except ProgrammingError as exc:
        if "permission denied to create role" not in str(exc).lower():
            raise
        pytest.skip(
            "SQL-level RLS smoke tests require a role with CREATEROLE to create "
            "the non-owner 'core_rls_smoke' test role. The compose/CI stack's "
            "skyrict superuser can; a non-superuser local skyrict cannot. "
            "Run the tests against the compose stack, or grant CREATEROLE to "
            'skyrict with: psql -U postgres -c "ALTER ROLE skyrict CREATEROLE"'
        )


class TestRlsFunction:
    async def test_current_tenant_id_exists(self, migrated_schema: None) -> None:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT public.current_tenant_id()"))
            assert result.scalar_one() is None  # unset GUC -> NULL

    async def test_guc_drives_function(self, migrated_schema: None) -> None:
        tenant_id = str(uuid.uuid4())
        async with engine.connect() as conn:
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (tenant_id,),
            )
            result = await conn.execute(text("SELECT public.current_tenant_id()"))
            assert result.scalar_one() == uuid.UUID(tenant_id)


class TestTwoTenantRls:
    async def test_tenant_b_cannot_read_tenant_a_rows(
        self, migrated_schema: None, rls_world: dict[str, str]
    ) -> None:
        await _ensure_rls_role()

        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET ROLE {RLS_ROLE}")

            # --- as tenant A ---
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (rls_world["tenant_a"],),
            )
            a_rows = (await conn.execute(text("SELECT id FROM core_roles"))).scalars().all()
            assert [str(row) for row in a_rows] == [rls_world["role_a"]]

            # --- as tenant B ---
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (rls_world["tenant_b"],),
            )
            b_rows = (await conn.execute(text("SELECT id FROM core_roles"))).scalars().all()
            b_ids = [str(row) for row in b_rows]
            assert b_ids == [rls_world["role_b"]]
            assert rls_world["role_a"] not in b_ids  # tenant B cannot read tenant A's rows

            await conn.exec_driver_sql("RESET ROLE")

        await engine.dispose()

    async def test_global_reference_tables_stay_readable(
        self, migrated_schema: None, rls_world: dict[str, str]
    ) -> None:
        await _ensure_rls_role()
        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET ROLE {RLS_ROLE}")
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (rls_world["tenant_a"],),
            )
            currencies = (
                (await conn.execute(text("SELECT code FROM erp_currencies"))).scalars().all()
            )
            assert "USD" in currencies
            await conn.exec_driver_sql("RESET ROLE")
        await engine.dispose()

    async def test_cross_tenant_insert_blocked_by_rls(
        self, migrated_schema: None, rls_world: dict[str, str]
    ) -> None:
        await _ensure_rls_role()

        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET ROLE {RLS_ROLE}")
            # Session GUC pinned to tenant A, but try to insert a row for B.
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (rls_world["tenant_a"],),
            )
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO core_roles (tenant_id, id, name, permissions) "
                        "VALUES (:tid, gen_random_uuid(), 'sneaky', '{}')"
                    ),
                    {"tid": uuid.UUID(rls_world["tenant_b"])},
                )
            assert "row-level security" in str(excinfo.value).lower()
            await conn.exec_driver_sql("RESET ROLE")

        await engine.dispose()


class TestCompositeFkConvention:
    async def test_cross_tenant_grant_rejected_by_fk_even_as_owner(
        self, migrated_schema: None, rls_world: dict[str, str]
    ) -> None:
        # The table owner bypasses RLS, so this can ONLY be stopped by the
        # composite FK (tenant_b, role_a) -> core_roles(tenant_b, id): role_a
        # belongs to tenant A, so the composite key doesn't exist. This is the
        # convention that makes referential integrity agree with RLS.
        async with engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO core_user_roles (tenant_id, id, user_id, role_id) "
                        "VALUES (:tenant_b, gen_random_uuid(), :user_id, :role_a)"
                    ),
                    {
                        "tenant_b": uuid.UUID(rls_world["tenant_b"]),
                        "user_id": uuid.UUID(rls_world["user_id"]),
                        "role_a": uuid.UUID(rls_world["role_a"]),
                    },
                )
            assert "fk_core_user_roles_role_tenant" in str(excinfo.value)

        await engine.dispose()


class TestSeededReferenceData:
    async def test_currencies_seeded(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            result = await session.execute(text("SELECT code FROM erp_currencies"))
            codes = result.scalars().all()
        assert "USD" in codes
        assert "EUR" in codes
        assert len(codes) >= 15

    async def test_permissions_seeded(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            result = await session.execute(text("SELECT key FROM core_permissions"))
            keys = result.scalars().all()
        assert "erp.inventory.read" in keys
        assert "erp.invoice.approve" in keys

    async def test_version_table_isolated(self, migrated_schema: None) -> None:
        """Core migrates under alembic_version_core; identity keeps alembic_version."""
        async with engine.connect() as conn:
            core_version = await conn.execute(text("SELECT version_num FROM alembic_version_core"))
            assert core_version.scalar_one() == "0001"
            identity_version = await conn.execute(text("SELECT 1 FROM alembic_version"))
            assert identity_version.scalar_one() == 1
