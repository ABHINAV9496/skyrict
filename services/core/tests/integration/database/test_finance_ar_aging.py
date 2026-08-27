"""Finance AR-aging report regression tests — verified against REAL Postgres.

``ar_aging`` derives outstanding receivables from issued/approved (unpaid)
invoices bucketed by ``due_date`` relative to an ``as_of`` date. Paid and
voided invoices must be excluded, and buckets must sum to ``total_ar`` with
shares proportional to amounts.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from core.db.session import async_session_factory, engine
from core.domain.value_objects import InvoiceStatus
from core.features.finance.models.invoice import ErpInvoiceModel
from core.features.finance.repository import FinanceRepository
from core.models.tenant import TenantModel

pytestmark = pytest.mark.integration

PIVOT = date(2026, 1, 31)


def _invoice_number(idx: int) -> str:
    return f"AR-{idx:04d}"


async def _seed_ar_tenant() -> str:
    """Seed one tenant plus a spread of AR invoices and return its id."""
    tenant_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    invoices = [
        # (invoice_number, status, due_date, total)
        ("AR-0001", InvoiceStatus.APPROVED, PIVOT + timedelta(days=5), Decimal("100.00")),
        ("AR-0002", InvoiceStatus.ISSUED, PIVOT + timedelta(days=10), Decimal("50.00")),
        ("AR-0003", InvoiceStatus.APPROVED, PIVOT - timedelta(days=10), Decimal("60.00")),
        ("AR-0004", InvoiceStatus.APPROVED, PIVOT - timedelta(days=45), Decimal("80.00")),
        ("AR-0005", InvoiceStatus.APPROVED, PIVOT - timedelta(days=75), Decimal("90.00")),
        ("AR-0006", InvoiceStatus.APPROVED, PIVOT - timedelta(days=120), Decimal("20.00")),
        # excluded: paid and voided
        ("AR-0007", InvoiceStatus.PAID, PIVOT - timedelta(days=200), Decimal("999.00")),
        ("AR-0008", InvoiceStatus.VOIDED, PIVOT - timedelta(days=200), Decimal("999.00")),
    ]
    async with async_session_factory() as session:
        session.add(
            TenantModel(
                id=tenant_id,
                name="AR Aging Tenant",
                slug=f"ar-{tenant_id.hex[:8]}",
                plan_tier="free",
                is_active=True,
            )
        )
        for num, status, due, total in invoices:
            session.add(
                ErpInvoiceModel(
                    tenant_id=tenant_id,
                    invoice_number=num,
                    customer_id=customer_id,
                    invoice_date=PIVOT - timedelta(days=30),
                    due_date=due,
                    status=status,
                    total=total,
                    source="manual",
                    source_ref=None,
                )
            )
        await session.commit()
        await engine.dispose()
    return str(tenant_id)


@pytest.fixture(scope="module")
def ar_world(migrated_schema: None) -> dict[str, str]:
    created = asyncio.run(_seed_ar_tenant())

    async def _teardown() -> None:
        async with async_session_factory() as session:
            await session.execute(
                text("DELETE FROM tenants WHERE id = :tid"), {"tid": uuid.UUID(created)}
            )
            await session.commit()
            await engine.dispose()

    try:
        yield {"tenant_id": created}
    finally:
        asyncio.run(_teardown())


def _bucket(report: object, key: str) -> tuple[int, Decimal, Decimal]:
    for b in report.buckets:
        if b.bucket == key:
            return b.count, b.amount, b.share
    return (0, Decimal("0"), Decimal("0"))


async def test_ar_aging_buckets_and_total(ar_world: dict[str, str]) -> None:
    tenant_id = uuid.UUID(ar_world["tenant_id"])
    async with async_session_factory() as session:
        repo = FinanceRepository(session)
        report = await repo.ar_aging(tenant_id, PIVOT)
        await session.rollback()

    assert report.as_of == PIVOT
    # only AR-0001..0006 are outstanding (750.00); paid/voided excluded
    assert report.total_ar == Decimal("750.00")

    current, cur_amt, cur_share = _bucket(report, "current")
    assert current == 2  # AR-0001, AR-0002 (due after pivot)
    assert cur_amt == Decimal("150.00")

    one_30, o30_amt, o30_share = _bucket(report, "1_30")
    assert one_30 == 1  # AR-0003 (10 days past)
    assert o30_amt == Decimal("60.00")

    s31_60, s60_amt, _ = _bucket(report, "31_60")
    assert s31_60 == 1  # AR-0004 (45 days past)
    assert s60_amt == Decimal("80.00")

    s61_90, s90_amt, _ = _bucket(report, "61_90")
    assert s61_90 == 1  # AR-0005 (75 days past)
    assert s90_amt == Decimal("90.00")

    over, over_amt, _ = _bucket(report, "over_90")
    assert over == 1  # AR-0006 (120 days past)
    assert over_amt == Decimal("20.00")

    # shares sum to ~1 and match proportions
    total_share = sum(b.share for b in report.buckets)
    assert abs(total_share - Decimal("1")) < Decimal("0.0001")
    assert cur_share == (Decimal("150") / Decimal("750")).quantize(Decimal("0.0001"))
    assert o30_share == (Decimal("60") / Decimal("750")).quantize(Decimal("0.0001"))


async def test_ar_aging_empty_tenant() -> None:
    tenant_id = uuid.uuid4()
    async with async_session_factory() as session:
        repo = FinanceRepository(session)
        report = await repo.ar_aging(tenant_id, PIVOT)
        await session.rollback()

    assert report.total_ar == Decimal("0")
    assert report.buckets == ()
