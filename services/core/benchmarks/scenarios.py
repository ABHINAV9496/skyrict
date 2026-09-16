"""Benchmark scenarios for SKY-99 - seed a fixed ERP dataset and expose cases.

Every case closure opens a FRESH session per invocation (mirroring a
request-scoped session) so the statement monitor never double-counts a reused
transaction and each sampled run measures an independent round trip.

The RLS GUC is deliberately NOT set here: the integration suite proves plain
``async_session_factory`` sessions read and write tenant rows unauthenticated
(cache RLS smoke tests use a separate role to *prove* the policy; the app/test
role is unconstrained), so benchmarks exercise the same path as the tests.

Reference closures encode the PRE-optimization query pattern (month loop,
serial balance-sheet loop, no cache) so the runner can assert the optimized
path is materially faster on the same machine/data - CI-stable because it
never depends on absolute machine speed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, TypedDict

from sqlalchemy import case, func, select

from core.db.session import async_session_factory
from core.domain.value_objects import AccountType, EntryStatus, InvoiceStatus
from core.features.finance.models.chart_of_account import ErpChartOfAccountModel
from core.features.finance.models.invoice import ErpInvoiceModel
from core.features.finance.models.journal_entry import ErpJournalEntryModel
from core.features.finance.models.journal_line import ErpJournalLineModel
from core.features.finance.models.tenant_setting import ErpTenantSettingModel
from core.features.finance.report_cache import ReportCacheRepository, hash_report_key
from core.features.finance.repository import FinanceRepository
from core.models.tenant import TenantModel

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

PIVOT = date(2026, 6, 30)

_currency = "USD"
_SOURCE = "benchmark"

# Matches core.features.finance.repository: projection looks 6 months FORWARD
# from ``as_of`` (Jun..Nov 2026 for PIVOT), so the naive reference reproduces
# the exact same window.
_forward_starts = [
    date(PIVOT.year + (PIVOT.month + i - 1) // 12, (PIVOT.month + i - 1) % 12 + 1, 1)
    for i in range(6)
]


def _end_of_month(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1) - timedelta(days=1)
    return date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)


def _past_month_end(i: int) -> date:
    """End date of the ``i``-th 1-indexed month ending before/at PIVOT."""
    return _end_of_month(
        date(PIVOT.year + (PIVOT.month - i - 1) // 12, (PIVOT.month - i - 1) % 12 + 1, 1)
    )


class BenchmarkWorld(TypedDict):
    """Seeded dataset identifiers shared by every case closure."""

    tenant_id: uuid.UUID


async def seed_benchmark_world() -> BenchmarkWorld:
    """Seed one tenant with posted entries + invoices around PIVOT."""

    async def _seed() -> BenchmarkWorld:
        tenant_id = uuid.uuid4()
        now = datetime.now(UTC)
        async with async_session_factory() as session:
            session.add(
                TenantModel(
                    id=tenant_id,
                    name="Benchmark Tenant",
                    slug=f"bench-{tenant_id.hex[:8]}",
                    plan_tier="free",
                    is_active=True,
                )
            )
            await session.flush()

            accounts: dict[str, ErpChartOfAccountModel] = {}
            for code, name, acct_type in (
                ("1100", "Cash", AccountType.ASSET),
                ("2000", "Accounts Payable", AccountType.LIABILITY),
                ("3000", "Retained Earnings", AccountType.EQUITY),
                ("4000", "Service Revenue", AccountType.REVENUE),
                ("5000", "Operating Expense", AccountType.EXPENSE),
            ):
                acc = ErpChartOfAccountModel(
                    tenant_id=tenant_id, code=code, name=name, account_type=acct_type
                )
                session.add(acc)
                accounts[code] = acc
            await session.flush()

            # 4 posted entries per past month; two share memo+date -> a real
            # duplicate group (windowed count > 2 across the tenant).
            for m in range(6):
                month_end = _past_month_end(m)
                for k in range(4):
                    memo = "Periodic close" if k < 2 else "Benchmark entry"
                    entry = ErpJournalEntryModel(
                        tenant_id=tenant_id,
                        entry_date=month_end - timedelta(days=3 if k >= 2 else 0),
                        memo=memo,
                        status=EntryStatus.POSTED,
                        source=_SOURCE,
                        source_ref=f"bench-{m}-{k}",
                        posted_at=now,
                    )
                    session.add(entry)
                    await session.flush()
                    session.add(
                        ErpJournalLineModel(
                            tenant_id=tenant_id,
                            entry_id=entry.id,
                            account_id=accounts["1100"].id,
                            debit=Decimal("100.00"),
                            credit=None,
                        )
                    )
                    session.add(
                        ErpJournalLineModel(
                            tenant_id=tenant_id,
                            entry_id=entry.id,
                            account_id=accounts["4000"].id,
                            debit=None,
                            credit=Decimal("100.00"),
                        )
                    )

            # Invoices spread from ~Mar to ~Sep 2026 so both the backward
            # (aging) and FORWARD (cashflow projection) windows aggregate data.
            customer_id = uuid.uuid4()
            statuses = (
                InvoiceStatus.ISSUED,
                InvoiceStatus.APPROVED,
                InvoiceStatus.PAID,
                InvoiceStatus.ISSUED,
                InvoiceStatus.APPROVED,
                InvoiceStatus.DRAFT,
            )
            for i in range(36):
                due_date = PIVOT + timedelta(days=-90 + i * 6)
                session.add(
                    ErpInvoiceModel(
                        tenant_id=tenant_id,
                        invoice_number=f"INV-{i:03d}",
                        customer_id=customer_id,
                        invoice_date=due_date - timedelta(days=30),
                        due_date=due_date,
                        status=statuses[i % 6],
                        total=Decimal(f"{100 + i}0.00"),
                        currency=_currency,
                    )
                )

            session.add(
                ErpTenantSettingModel(
                    tenant_id=tenant_id,
                    key="benchmark.lane",
                    value="arm",
                )
            )
            await session.commit()
        return {"tenant_id": tenant_id}

    return await _seed()


async def destroy_benchmark_world(world: BenchmarkWorld) -> None:
    """Delete the seeded tenant (FK cascade removes its rows)."""
    async with async_session_factory() as session:
        await session.delete(await session.get(TenantModel, world["tenant_id"]))
        await session.commit()


# ---------------------------------------------------------------------------
# Case closures (each invocation opens a fresh session)
# ---------------------------------------------------------------------------


def _repo_call(
    tenant_id: uuid.UUID,
    fn: Callable[[FinanceRepository], Awaitable[object]],
) -> Callable[[], Awaitable[object]]:
    async def _call() -> object:
        async with async_session_factory() as session:
            return await fn(FinanceRepository(session))

    return _call


def cashflow_projection_case(tenant_id: uuid.UUID) -> Callable[[], Awaitable[object]]:
    return _repo_call(tenant_id, lambda r: r.cashflow_projection(tenant_id, PIVOT))


def cashflow_naive_loop(tenant_id: uuid.UUID) -> Callable[[], Awaitable[object]]:
    """Pre-optimization shape: one (month-scoped) aggregate query per month."""

    async def _call() -> object:
        async with async_session_factory() as session:
            for month_start in _forward_starts:
                stmt = select(
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    ErpInvoiceModel.status.in_(
                                        [InvoiceStatus.ISSUED, InvoiceStatus.APPROVED]
                                    ),
                                    ErpInvoiceModel.total,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    ErpInvoiceModel.status == InvoiceStatus.ISSUED,
                                    ErpInvoiceModel.total,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                ).where(
                    ErpInvoiceModel.tenant_id == tenant_id,
                    ErpInvoiceModel.status.in_([InvoiceStatus.ISSUED, InvoiceStatus.APPROVED]),
                    ErpInvoiceModel.due_date >= month_start,
                    ErpInvoiceModel.due_date <= _end_of_month(month_start),
                )
                await session.execute(stmt)
        return None

    return _call


def duplicates_case(tenant_id: uuid.UUID) -> Callable[[], Awaitable[object]]:
    return _repo_call(tenant_id, lambda r: r.duplicates(tenant_id))


def working_capital_series_case(tenant_id: uuid.UUID) -> Callable[[], Awaitable[object]]:
    return _repo_call(tenant_id, lambda r: r.working_capital_series(tenant_id, PIVOT, months=6))


def working_capital_serial(tenant_id: uuid.UUID) -> Callable[[], Awaitable[object]]:
    """Pre-optimization shape: six sequential as-of balance-sheet queries."""

    async def _call() -> object:
        async with async_session_factory() as session:
            repo = FinanceRepository(session)
            for i in range(6):
                await repo.balance_sheet(tenant_id, _past_month_end(i))
        return None

    return _call


_CACHE_HIT_KEY = "bench|cache_hit"


async def seed_cache_hit(world: BenchmarkWorld) -> None:
    """Store one live cache row so the hit case measures only the GET."""
    tenant_id = world["tenant_id"]
    key = hash_report_key(_CACHE_HIT_KEY, str(tenant_id))
    async with async_session_factory() as session:
        repo = ReportCacheRepository(session)
        await repo.put(
            tenant_id=tenant_id,
            cache_key=key,
            payload={"net": "12345.00", "bucket": "arm"},
        )
        await session.commit()


def report_cache_hit_case(tenant_id: uuid.UUID) -> Callable[[], Awaitable[object]]:
    key = hash_report_key(_CACHE_HIT_KEY, str(tenant_id))

    async def _call() -> object:
        async with async_session_factory() as session:
            got = await ReportCacheRepository(session).get(tenant_id=tenant_id, cache_key=key)
            if got is None:
                raise AssertionError("cache hit case found no cached row")
        return None

    return _call


def report_aggregate_recompute(tenant_id: uuid.UUID) -> Callable[[], Awaitable[object]]:
    """What a dashboard read costs WITHOUT the cache (one aggregate query)."""
    return _repo_call(tenant_id, lambda r: r.balance_sheet(tenant_id, PIVOT))


def report_cache_miss_case(tenant_id: uuid.UUID) -> Callable[[], Awaitable[object]]:
    """Cache-miss round trip: miss GET + compute + write-with-upsert."""

    async def _call() -> object:
        key = hash_report_key("bench|cache_miss", uuid.uuid4().hex)
        async with async_session_factory() as session:
            repo = ReportCacheRepository(session)
            hit = await repo.get(tenant_id=tenant_id, cache_key=key)
            if hit is not None:
                raise AssertionError("cache miss case unexpectedly hit")
            res = await FinanceRepository(session).balance_sheet(tenant_id, PIVOT)
            await repo.put(
                tenant_id=tenant_id,
                cache_key=key,
                payload={"net": str(res.total_assets - res.total_liabilities)},
            )
            await session.commit()
        return None

    return _call
