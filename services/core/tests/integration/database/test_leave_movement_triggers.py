"""Behavioral DB tests for migration 0009's leave-ledger triggers (gap item 11).

Proves the append-only and non-negative guarantees at the SQL layer against
REAL Postgres — not through the service:

  - a positive accrual INSERT succeeds;
  - an INSERT that would push the per-(tenant, employee, leave_type) SUM
    negative is rejected and fully rolled back;
  - landing exactly on zero is allowed;
  - direct UPDATE / DELETE of a ledger row is rejected (append-only).

The dev ``skyrict`` superuser bypasses RLS, so rows are written straight via
SQL; the triggers fire at trigger depth 1, which is exactly the path the
negative-guard and append-only functions are designed to guard.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from core.db.session import async_session_factory, engine
from core.features.hr.models.employee import EmployeeModel
from core.features.hr.models.leave_type import LeaveTypeModel
from core.models.tenant import TenantModel

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def leave_ledger_world(migrated_schema: None) -> dict[str, str]:
    """Seed one tenant + accrual leave type; each test creates its own employee.

    Plain (sync) fixture: all DB work runs inside one ``asyncio.run()`` and the
    engine pool is disposed before that run's loop closes, so the function-
    scoped async tests that follow get a clean pool bound to their own loops.
    """

    async def _setup() -> dict[str, str]:
        tenant_id = str(uuid.uuid4())
        leave_type_id = str(uuid.uuid4())

        async with async_session_factory() as session:
            session.add(
                TenantModel(
                    id=uuid.UUID(tenant_id),
                    name="Ledger Tenant",
                    slug=f"ledger-{tenant_id[:8]}",
                    plan_tier="free",
                    is_active=True,
                )
            )
            await session.flush()
            session.add(
                LeaveTypeModel(
                    tenant_id=uuid.UUID(tenant_id),
                    id=uuid.UUID(leave_type_id),
                    code="annual",
                    name="Annual Leave",
                    is_accrual=True,
                    accrual_days_per_year=20,
                )
            )
            await session.commit()
        await engine.dispose()
        return {
            "tenant_id": tenant_id,
            "leave_type": "annual",
        }

    return asyncio.run(_setup())


async def _new_employee(session, tenant_id: str) -> str:
    employee_id = uuid.uuid4()
    session.add(
        EmployeeModel(
            tenant_id=uuid.UUID(tenant_id),
            id=employee_id,
            employee_number=f"LDG-{employee_id.hex[:8]}",
            first_name="Ledger",
            last_name="Test",
            job_title="Engineer",
            hire_date=date(2024, 1, 1),
        )
    )
    await session.commit()
    return str(employee_id)


async def _insert(session, tenant_id: str, employee_id: str, *, qty: int) -> str:
    movement_id = str(uuid.uuid4())
    await session.execute(
        text(
            "INSERT INTO public.erp_leave_movements "
            "(tenant_id, id, employee_id, leave_type, qty, ref_type, ref_id) "
            "VALUES (:tenant_id, :id, :employee_id, :leave_type, :qty, :ref_type, :ref_id)"
        ),
        {
            "tenant_id": tenant_id,
            "id": movement_id,
            "employee_id": employee_id,
            "leave_type": "annual",
            "qty": qty,
            "ref_type": "annual_accrual",
            "ref_id": "2026",
        },
    )
    await session.commit()
    return movement_id


async def _sum(session, tenant_id: str, employee_id: str) -> int:
    result = await session.execute(
        text(
            "SELECT COALESCE(SUM(qty), 0) FROM public.erp_leave_movements "
            "WHERE tenant_id = :tenant_id AND employee_id = :employee_id"
        ),
        {"tenant_id": tenant_id, "employee_id": employee_id},
    )
    return int(result.scalar_one())


class TestLeaveLedgerTriggers:
    async def test_positive_accrual_insert_succeeds(self, leave_ledger_world) -> None:
        tenant_id = leave_ledger_world["tenant_id"]
        async with async_session_factory() as session:
            employee_id = await _new_employee(session, tenant_id)
            movement_id = await _insert(session, tenant_id, employee_id, qty=15)
            assert await _sum(session, tenant_id, employee_id) == 15
            assert (
                await session.execute(
                    text("SELECT 1 FROM public.erp_leave_movements WHERE id = :id"),
                    {"id": movement_id},
                )
            ).scalar_one() == 1

    async def test_negative_balance_insert_rejected_and_rolled_back(
        self, leave_ledger_world
    ) -> None:
        tenant_id = leave_ledger_world["tenant_id"]
        async with async_session_factory() as session:
            employee_id = await _new_employee(session, tenant_id)
            await _insert(session, tenant_id, employee_id, qty=10)
            with pytest.raises(SQLAlchemyError, match="negative"):
                await _insert(session, tenant_id, employee_id, qty=-20)
            await session.rollback()
            assert await _sum(session, tenant_id, employee_id) == 10

    async def test_landing_exactly_on_zero_is_allowed(self, leave_ledger_world) -> None:
        tenant_id = leave_ledger_world["tenant_id"]
        async with async_session_factory() as session:
            employee_id = await _new_employee(session, tenant_id)
            await _insert(session, tenant_id, employee_id, qty=8)
            await _insert(session, tenant_id, employee_id, qty=-8)
            assert await _sum(session, tenant_id, employee_id) == 0

    async def test_direct_update_rejected(self, leave_ledger_world) -> None:
        tenant_id = leave_ledger_world["tenant_id"]
        async with async_session_factory() as session:
            employee_id = await _new_employee(session, tenant_id)
            movement_id = await _insert(session, tenant_id, employee_id, qty=15)
            with pytest.raises(SQLAlchemyError, match="append-only"):
                await session.execute(
                    text("UPDATE public.erp_leave_movements SET qty = 0 WHERE id = :id"),
                    {"id": movement_id},
                )
            await session.rollback()
            assert await _sum(session, tenant_id, employee_id) == 15

    async def test_direct_delete_rejected(self, leave_ledger_world) -> None:
        tenant_id = leave_ledger_world["tenant_id"]
        async with async_session_factory() as session:
            employee_id = await _new_employee(session, tenant_id)
            movement_id = await _insert(session, tenant_id, employee_id, qty=15)
            with pytest.raises(SQLAlchemyError, match="append-only"):
                await session.execute(
                    text("DELETE FROM public.erp_leave_movements WHERE id = :id"),
                    {"id": movement_id},
                )
            await session.rollback()
            assert await _sum(session, tenant_id, employee_id) == 15
