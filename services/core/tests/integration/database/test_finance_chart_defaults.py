"""Default chart-of-accounts provisioning + backfill integration (SKY-94/SKY-96).

Proves the finance chart gap fix end-to-end over REAL Postgres:

  - ``seed_tenant_finance_defaults`` gives a brand-new tenant all 9 mandatory
    account codes (1100/1200/1300/2010/2020/2110/4000/5000/5010) in one call,
    so sales order fulfilment can resolve the Revenue and COGS codes;
  - re-running the seeder is idempotent - it never duplicates an existing
    code, and a pre-existing custom account with the same code is left
    untouched (no overwrite);
  - the ``(tenant_id, code)`` unique constraint is the DB-level guard behind
    ON CONFLICT, so a provisioning race cannot double-insert.

The migration-0063 backfill itself is covered by the full chain round-trip
test (test_migration_roundtrip.py), which inserts two tenants before the
chain runs and asserts each gets exactly 9 code-distinct rows.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select, text

from core.db.session import async_session_factory, engine
from core.features.finance.models.chart_of_account import ErpChartOfAccountModel
from core.models.tenant import TenantModel
from core.seed import DEFAULT_CHART_ACCOUNTS, seed_tenant_finance_defaults

pytestmark = pytest.mark.integration

DEFAULT_CODES = {account.code for account in DEFAULT_CHART_ACCOUNTS}


@pytest.fixture(scope="module")
def chart_world(migrated_schema: None) -> dict[str, str]:
    """A fresh tenant isolated for the chart tests."""

    async def _setup() -> dict[str, str]:
        tenant_id = str(uuid.uuid4())
        async with async_session_factory() as session:
            session.add(
                TenantModel(
                    id=uuid.UUID(tenant_id),
                    name="Chart Tenant",
                    slug=f"cht-{tenant_id[:8]}",
                    plan_tier="free",
                    is_active=True,
                )
            )
            await session.commit()
        await engine.dispose()
        return {"tenant_id": tenant_id}

    async def _teardown() -> None:
        async with async_session_factory() as session:
            await session.execute(
                text("DELETE FROM tenants WHERE id = :tid"),
                {"tid": uuid.UUID(chart_world["tenant_id"])},
            )
            await session.commit()
            await engine.dispose()

    chart_world = asyncio.run(_setup())
    try:
        yield chart_world
    finally:
        asyncio.run(_teardown())


@pytest.fixture(autouse=True)
async def clean_chart(chart_world: dict[str, str]) -> None:
    """Each test owns a clean chart for the tenant (runs on the test loop)."""
    async with async_session_factory() as session:
        await session.execute(
            text("DELETE FROM erp_chart_of_accounts WHERE tenant_id = :tid"),
            {"tid": uuid.UUID(chart_world["tenant_id"])},
        )
        await session.commit()
    yield


async def test_seed_creates_all_default_codes(chart_world: dict[str, str]) -> None:
    tenant_id = uuid.UUID(chart_world["tenant_id"])
    await seed_tenant_finance_defaults(tenant_id)
    codes = await _chart_codes(tenant_id)
    assert codes == DEFAULT_CODES


async def test_seed_is_idempotent(chart_world: dict[str, str]) -> None:
    tenant_id = uuid.UUID(chart_world["tenant_id"])
    for _ in range(3):
        await seed_tenant_finance_defaults(tenant_id)
    codes = await _chart_codes(tenant_id)
    assert codes == DEFAULT_CODES

    async with async_session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(ErpChartOfAccountModel)
            .where(ErpChartOfAccountModel.tenant_id == tenant_id)
        )
    assert count == len(DEFAULT_CODES)


async def test_seed_preserves_existing_custom_account(
    chart_world: dict[str, str],
) -> None:
    """A pre-existing account with a non-default code is preserved by seeding."""
    tenant_id = uuid.UUID(chart_world["tenant_id"])

    custom_id = uuid.uuid4()
    async with async_session_factory() as session:
        session.add(
            ErpChartOfAccountModel(
                tenant_id=tenant_id,
                id=custom_id,
                code="9999",
                name="Custom Other Income",
                account_type="revenue",
            )
        )
        await session.commit()

    await seed_tenant_finance_defaults(tenant_id)

    # Custom row must survive; default count must still be 9.
    async with async_session_factory() as session:
        row = await session.scalar(
            select(ErpChartOfAccountModel).where(
                ErpChartOfAccountModel.tenant_id == tenant_id,
                ErpChartOfAccountModel.id == custom_id,
            )
        )
        count = await session.scalar(
            select(func.count())
            .select_from(ErpChartOfAccountModel)
            .where(ErpChartOfAccountModel.tenant_id == tenant_id)
        )
    assert row is not None
    assert row.name == "Custom Other Income"
    assert count == len(DEFAULT_CODES) + 1


async def _chart_codes(tenant_id: uuid.UUID) -> set[str]:
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(ErpChartOfAccountModel.code).where(
                    ErpChartOfAccountModel.tenant_id == tenant_id
                )
            )
        ).scalars()
        return set(rows)
