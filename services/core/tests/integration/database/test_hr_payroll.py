"""HR/Payroll integration tests (HR-DATA-001) - real Postgres, real migrations.

Covers what a model test cannot:

  - RLS on the new ``erp_*`` tables: a non-owner role (``core_rls_smoke``)
    plus the ``app.current_tenant_id`` GUC sees only its own tenant's rows;
  - cross-tenant INSERTs rejected by RLS ``WITH CHECK``;
  - the composite-FK convention blocking a cross-tenant child row even as the
    table OWNER (referential integrity agrees with RLS);
  - DB CHECKs (leave balance >= 0, terminated requires termination_date);
  - the partial unique index forbidding two non-void runs on one period;
  - the native enum types created by migration 0005.

Skipped automatically when Postgres is unreachable (``migrated_schema``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from core.db.session import async_session_factory, engine
from core.features.hr.models.employee import EmployeeModel
from core.features.hr.models.leave_type import LeaveTypeModel
from core.models.tenant import TenantModel

pytestmark = pytest.mark.integration

RLS_ROLE = "core_rls_smoke"

_ERP_CHILD_TABLES = (
    "erp_payroll_entries",
    "erp_payroll_runs",
    "erp_compensation",
    "erp_leave_balances",
    "erp_leave_movements",
    "erp_leave_requests",
    "erp_employees",
    "erp_departments",
    "erp_leave_types",
)


@pytest.fixture(scope="module")
def erp_world(migrated_schema: None) -> dict[str, str]:
    """Seed two tenants; tenant A gets an employee + annual leave type.

    Plain (sync) fixture: all DB work runs inside one ``asyncio.run()`` and
    the engine pool is disposed before that run's loop closes, so the
    function-scoped async tests that follow get a clean pool bound to their
    own loops.
    """

    async def _setup() -> dict[str, str]:
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        employee_a = str(uuid.uuid4())

        async with async_session_factory() as session:
            session.add_all(
                [
                    TenantModel(
                        id=uuid.UUID(tenant_a),
                        name="ERP Tenant A",
                        slug=f"erp-a-{tenant_a[:8]}",
                        plan_tier="free",
                        is_active=True,
                    ),
                    TenantModel(
                        id=uuid.UUID(tenant_b),
                        name="ERP Tenant B",
                        slug=f"erp-b-{tenant_b[:8]}",
                        plan_tier="free",
                        is_active=True,
                    ),
                ]
            )
            await session.flush()
            # Same employee number in both tenants - uniqueness is per-tenant.
            session.add_all(
                [
                    EmployeeModel(
                        tenant_id=uuid.UUID(tenant_a),
                        id=uuid.UUID(employee_a),
                        employee_number="EMP-0001",
                        first_name="Alice",
                        last_name="Anderson",
                        job_title="Engineer",
                        hire_date=date(2025, 1, 1),
                    ),
                    EmployeeModel(
                        tenant_id=uuid.UUID(tenant_b),
                        id=uuid.uuid4(),
                        employee_number="EMP-0001",
                        first_name="Bob",
                        last_name="Brown",
                        job_title="Engineer",
                        hire_date=date(2025, 1, 1),
                    ),
                    # Annual leave type in BOTH tenants, so FK tests differ only
                    # by tenant - never by a missing catalogue entry.
                    LeaveTypeModel(
                        tenant_id=uuid.UUID(tenant_a),
                        id=uuid.uuid4(),
                        code="annual",
                        name="Annual Leave",
                        is_accrual=True,
                        accrual_days_per_year=20,
                    ),
                    LeaveTypeModel(
                        tenant_id=uuid.UUID(tenant_b),
                        id=uuid.uuid4(),
                        code="annual",
                        name="Annual Leave",
                        is_accrual=True,
                        accrual_days_per_year=20,
                    ),
                ]
            )
            await session.commit()
            await engine.dispose()

        return {
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "employee_a": employee_a,
        }

    async def _teardown() -> None:
        # Children first (NO ACTION FKs), then the tenants themselves.
        async with async_session_factory() as session:
            for tid in (erp_world_data["tenant_a"], erp_world_data["tenant_b"]):
                for table in _ERP_CHILD_TABLES:
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE tenant_id = :tid"),
                        {"tid": uuid.UUID(tid)},
                    )
                await session.execute(
                    text("DELETE FROM tenants WHERE id = :tid"), {"tid": uuid.UUID(tid)}
                )
            await session.commit()
            await engine.dispose()

    erp_world_data = asyncio.run(_setup())
    try:
        yield erp_world_data
    finally:
        asyncio.run(_teardown())


async def _ensure_erp_rls_role() -> None:
    """Create the non-owner RLS test role + grants on the erp tables it reads.

    The dev ``skyrict`` user owns the tables (and bypasses RLS), so a
    NON-OWNER role is needed to prove the policies bite. Skipped with an
    actionable message when the local ``skyrict`` lacks CREATEROLE.
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
            for table in (
                "erp_employees",
                "erp_leave_requests",
                "erp_leave_balances",
                "erp_leave_movements",
                "erp_leave_types",
                "erp_departments",
            ):
                await conn.exec_driver_sql(f"GRANT SELECT ON TABLE public.{table} TO {RLS_ROLE}")
            await conn.exec_driver_sql(f"GRANT INSERT ON TABLE public.erp_employees TO {RLS_ROLE}")
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


class TestErpRls:
    async def test_tenant_b_cannot_read_tenant_a_employees(
        self, migrated_schema: None, erp_world: dict[str, str]
    ) -> None:
        await _ensure_erp_rls_role()

        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET ROLE {RLS_ROLE}")

            # --- as tenant A: only tenant A's employee is visible ---
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (erp_world["tenant_a"],),
            )
            a_ids = (await conn.execute(text("SELECT id FROM erp_employees"))).scalars().all()
            assert [str(row) for row in a_ids] == [erp_world["employee_a"]]

            # --- as tenant B: tenant A's employee is invisible ---
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (erp_world["tenant_b"],),
            )
            b_ids = (await conn.execute(text("SELECT id FROM erp_employees"))).scalars().all()
            b_str = [str(row) for row in b_ids]
            assert len(b_str) == 1
            assert erp_world["employee_a"] not in b_str

            await conn.exec_driver_sql("RESET ROLE")

        await engine.dispose()

    async def test_tenant_a_cannot_read_tenant_b_leave_types(
        self, migrated_schema: None, erp_world: dict[str, str]
    ) -> None:
        await _ensure_erp_rls_role()

        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET ROLE {RLS_ROLE}")
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (erp_world["tenant_a"],),
            )
            a_types = (await conn.execute(text("SELECT code FROM erp_leave_types"))).scalars().all()
            assert a_types == ["annual"]  # tenant A's own catalogue entry
            await conn.exec_driver_sql("RESET ROLE")

        await engine.dispose()

    async def test_cross_tenant_insert_blocked_by_rls(
        self, migrated_schema: None, erp_world: dict[str, str]
    ) -> None:
        await _ensure_erp_rls_role()

        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET ROLE {RLS_ROLE}")
            # GUC pinned to tenant A, but the INSERT targets tenant B.
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (erp_world["tenant_a"],),
            )
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_employees "
                        "(tenant_id, id, employee_number, first_name, last_name, "
                        "job_title, hire_date) "
                        "VALUES (:tid, gen_random_uuid(), 'EMP-SNEAKY', 'Sneaky', "
                        "'Person', 'Engineer', '2026-01-01')"
                    ),
                    {"tid": uuid.UUID(erp_world["tenant_b"])},
                )
            assert "row-level security" in str(excinfo.value).lower()
            await conn.rollback()
            await conn.exec_driver_sql("RESET ROLE")

        await engine.dispose()


class TestErpCompositeFkConvention:
    async def test_cross_tenant_leave_request_rejected_even_as_owner(
        self, migrated_schema: None, erp_world: dict[str, str]
    ) -> None:
        # The table owner bypasses RLS, so this can ONLY be stopped by the
        # composite FK (tenant_b, employee_a) -> erp_employees(tenant_b, id):
        # employee_a belongs to tenant A, so the composite key doesn't exist.
        # The annual leave type DOES exist in tenant B - so the employee FK is
        # the only constraint that can fire, keeping the assertion deterministic.
        async with engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_leave_requests "
                        "(tenant_id, id, employee_id, leave_type, start_date, "
                        "end_date, days) "
                        "VALUES (:tenant_b, gen_random_uuid(), :employee_a, "
                        "'annual', '2026-02-01', '2026-02-02', 2)"
                    ),
                    {
                        "tenant_b": uuid.UUID(erp_world["tenant_b"]),
                        "employee_a": uuid.UUID(erp_world["employee_a"]),
                    },
                )
            assert "fk_erp_leave_requests_employee" in str(excinfo.value)

        await engine.dispose()


class TestErpConstraints:
    async def test_leave_balance_cannot_go_negative(
        self, migrated_schema: None, erp_world: dict[str, str]
    ) -> None:
        async with engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_leave_balances "
                        "(tenant_id, id, employee_id, leave_type, balance) "
                        "VALUES (:tid, gen_random_uuid(), :emp, 'annual', -1)"
                    ),
                    {
                        "tid": uuid.UUID(erp_world["tenant_a"]),
                        "emp": uuid.UUID(erp_world["employee_a"]),
                    },
                )
            assert "ck_erp_leave_balances_non_negative" in str(excinfo.value)

        await engine.dispose()

    async def test_terminated_employee_requires_termination_date(
        self, migrated_schema: None, erp_world: dict[str, str]
    ) -> None:
        async with engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_employees "
                        "(tenant_id, id, employee_number, first_name, last_name, "
                        "job_title, hire_date, employment_status) "
                        "VALUES (:tid, gen_random_uuid(), 'EMP-QUIT', 'Quit', "
                        "'Quickly', 'Engineer', '2025-06-01', 'terminated')"
                    ),
                    {"tid": uuid.UUID(erp_world["tenant_a"])},
                )
            assert "ck_erp_employees_termination_required" in str(excinfo.value)

        await engine.dispose()

    async def test_two_active_runs_on_same_period_rejected(
        self, migrated_schema: None, erp_world: dict[str, str]
    ) -> None:
        async with engine.connect() as conn:
            # First run for the period - ok.
            await conn.execute(
                text(
                    "INSERT INTO erp_payroll_runs "
                    "(tenant_id, id, run_code, period_start, period_end) "
                    "VALUES (:tid, gen_random_uuid(), 'PR-0001', "
                    "'2026-01-01', '2026-01-31')"
                ),
                {"tid": uuid.UUID(erp_world["tenant_a"])},
            )
            # Second non-void run for the same period - blocked by the partial
            # unique index (WHERE status <> 'void').
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_payroll_runs "
                        "(tenant_id, id, run_code, period_start, period_end) "
                        "VALUES (:tid, gen_random_uuid(), 'PR-0002', "
                        "'2026-01-01', '2026-01-31')"
                    ),
                    {"tid": uuid.UUID(erp_world["tenant_a"])},
                )
            assert "uq_erp_payroll_runs_period_active" in str(excinfo.value)

            # Roll back the aborted transaction before continuing.
            await conn.rollback()

            # A VOID run may overlap - the index excludes voided rows.
            await conn.execute(
                text(
                    "INSERT INTO erp_payroll_runs "
                    "(tenant_id, id, run_code, period_start, period_end, status) "
                    "VALUES (:tid, gen_random_uuid(), 'PR-VOID', "
                    "'2026-01-01', '2026-01-31', 'void')"
                ),
                {"tid": uuid.UUID(erp_world["tenant_a"])},
            )

        await engine.dispose()


class TestErpNativeEnums:
    async def test_migration_created_enum_types(
        self, migrated_schema: None, erp_world: dict[str, str]
    ) -> None:
        async with engine.connect() as conn:
            employment = (
                (
                    await conn.execute(
                        text("SELECT unnest(enum_range(NULL::erp_employment_status))::text")
                    )
                )
                .scalars()
                .all()
            )
            assert sorted(employment) == ["active", "on_leave", "terminated"]

            leave_status = (
                (
                    await conn.execute(
                        text("SELECT unnest(enum_range(NULL::erp_leave_request_status))::text")
                    )
                )
                .scalars()
                .all()
            )
            assert sorted(leave_status) == ["approved", "cancelled", "pending", "rejected"]

            run_status = (
                (
                    await conn.execute(
                        text("SELECT unnest(enum_range(NULL::erp_payroll_run_status))::text")
                    )
                )
                .scalars()
                .all()
            )
            assert sorted(run_status) == ["approved", "computed", "draft", "paid", "void"]

            rounding = (
                (
                    await conn.execute(
                        text("SELECT unnest(enum_range(NULL::erp_payroll_rounding))::text")
                    )
                )
                .scalars()
                .all()
            )
            assert sorted(rounding) == ["down", "nearest", "up"]

        await engine.dispose()
