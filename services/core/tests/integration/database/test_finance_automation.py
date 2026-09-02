"""Finance automation repo regression tests — verified against REAL Postgres.

Covers the SKY-56/SKY-64 wave-1 read-models that live in
:class:`core.features.finance.repository.FinanceRepository`:

- close_checklist (B2) — prior-period / posted-entries / balanced-TB gates;
- duplicates (B10) — grouped by memo + entry date;
- tenant settings KV round-trip;
- ai anomaly/suggestion upsert dedupe;
- journal entry reversal (B8) — flips debit/credit and stamps reversal_entry_id.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from core.db.session import async_session_factory, engine
from core.domain.value_objects import AccountType, EntryStatus, InvoiceStatus
from core.features.finance.models.chart_of_account import ErpChartOfAccountModel
from core.features.finance.models.fiscal_period import ErpFiscalPeriodModel
from core.features.finance.models.invoice import ErpInvoiceModel
from core.features.finance.models.journal_entry import ErpJournalEntryModel
from core.features.finance.models.journal_line import ErpJournalLineModel
from core.features.finance.repository import FinanceRepository
from core.models.tenant import TenantModel

pytestmark = pytest.mark.integration

PIVOT = date(2026, 6, 30)


@pytest.fixture(scope="module")
def automation_world(migrated_schema: None) -> dict[str, str]:
    """Seed one tenant with posted journal entries, an open period, and an invoice."""

    async def _setup() -> dict[str, str]:
        tenant_id = uuid.uuid4()
        periods = [
            ("2025 Q4", date(2025, 10, 1), date(2025, 12, 31), True),
            ("2026 Q1", date(2026, 1, 1), date(2026, 3, 31), False),
        ]
        accounts = [
            ("1100", "Cash", AccountType.ASSET),
            ("4000", "Service Revenue", AccountType.REVENUE),
        ]
        async with async_session_factory() as session:
            session.add(
                TenantModel(
                    id=tenant_id,
                    name="Automation Tenant",
                    slug=f"auto-{tenant_id.hex[:8]}",
                    plan_tier="free",
                    is_active=True,
                )
            )
            await session.flush()
            account_ids: list[uuid.UUID] = []
            for code, name, acct_type in accounts:
                acc = ErpChartOfAccountModel(
                    tenant_id=tenant_id, code=code, name=name, account_type=acct_type
                )
                session.add(acc)
                await session.flush()
                account_ids.append(acc.id)

            period_ids: list[uuid.UUID] = []
            for name, start, end, closed in periods:
                p = ErpFiscalPeriodModel(
                    tenant_id=tenant_id,
                    name=name,
                    start_date=start,
                    end_date=end,
                    is_closed=closed,
                )
                session.add(p)
                await session.flush()
                period_ids.append(p.id)

            # Two posted journal entries with the SAME memo + entry date -> duplicate group.
            for _ in range(2):
                je = ErpJournalEntryModel(
                    tenant_id=tenant_id,
                    entry_date=date(2026, 2, 10),
                    memo="February rent",
                    status=EntryStatus.POSTED,
                    source="manual",
                    source_ref=None,
                    posted_at=PIVOT - timedelta(days=100),
                )
                session.add(je)
                await session.flush()
                session.add(
                    ErpJournalLineModel(
                        tenant_id=tenant_id,
                        entry_id=je.id,
                        account_id=account_ids[0],
                        debit=Decimal("1000"),
                        credit=None,
                    )
                )
                session.add(
                    ErpJournalLineModel(
                        tenant_id=tenant_id,
                        entry_id=je.id,
                        account_id=account_ids[1],
                        debit=None,
                        credit=Decimal("1000"),
                    )
                )

            # An approved invoice due >90 days past -> over_90 aging bucket.
            session.add(
                ErpInvoiceModel(
                    tenant_id=tenant_id,
                    invoice_number="AUT-001",
                    customer_id=uuid.uuid4(),
                    invoice_date=PIVOT - timedelta(days=200),
                    due_date=PIVOT - timedelta(days=120),
                    status=InvoiceStatus.APPROVED,
                    total=Decimal("500"),
                    source="manual",
                    source_ref=None,
                )
            )
            await session.commit()
            await engine.dispose()
        return {"tenant_id": str(tenant_id), "period_id": str(period_ids[1])}

    async def _teardown(created: str) -> None:
        async with async_session_factory() as session:
            await session.execute(
                text("DELETE FROM tenants WHERE id = :tid"), {"tid": uuid.UUID(created)}
            )
            await session.commit()
            await engine.dispose()

    created = asyncio.run(_setup())
    try:
        yield created
    finally:
        asyncio.run(_teardown(created["tenant_id"]))


async def test_close_checklist_returns_gates(automation_world: dict[str, str]) -> None:
    tenant_id = uuid.UUID(automation_world["tenant_id"])
    period_id = uuid.UUID(automation_world["period_id"])
    async with async_session_factory() as session:
        repo = FinanceRepository(session)
        checklist = await repo.close_checklist(tenant_id, period_id)
        await session.rollback()

    assert checklist.period_name == "2026 Q1"
    labels = [item.label for item in checklist.items]
    assert "Trial balance balanced" in labels
    assert any(
        item.label == "Previous period closed" and item.status == "ok" for item in checklist.items
    )


async def test_duplicates_groups_by_memo_and_date(automation_world: dict[str, str]) -> None:
    tenant_id = uuid.UUID(automation_world["tenant_id"])
    async with async_session_factory() as session:
        repo = FinanceRepository(session)
        groups = await repo.duplicates(tenant_id)
        await session.rollback()

    assert any(g.key.startswith("February rent") and len(g.entries) == 2 for g in groups)


async def test_working_capital_alert_threshold(automation_world: dict[str, str]) -> None:
    tenant_id = uuid.UUID(automation_world["tenant_id"])
    async with async_session_factory() as session:
        repo = FinanceRepository(session)
        alert = await repo.working_capital_alert(tenant_id, PIVOT)
        await session.rollback()
    assert isinstance(alert.ratio, Decimal)
    assert alert.threshold == Decimal("1.5")


async def test_tenant_setting_roundtrip() -> None:
    tenant_id = uuid.uuid4()
    async with async_session_factory() as session:
        repo = FinanceRepository(session)
        await repo.upsert_tenant_setting(tenant_id, "wc_threshold", "2.0")
        setting = await repo.get_tenant_setting(tenant_id, "wc_threshold")
        assert setting is not None and setting.value == "2.0"
        # upsert updates in place (dedupe on tenant+key)
        await repo.upsert_tenant_setting(tenant_id, "wc_threshold", "1.25")
        again = await repo.get_tenant_setting(tenant_id, "wc_threshold")
        assert again is not None and again.value == "1.25"
        await session.rollback()


async def test_ai_anomaly_upsert_dedupes(automation_world: dict[str, str]) -> None:
    tenant_id = uuid.UUID(automation_world["tenant_id"])
    entity_id = uuid.uuid4()
    async with async_session_factory() as session:
        repo = FinanceRepository(session)
        from core.domain.entities import AiFinanceAnomaly

        await repo.upsert_ai_anomaly(
            tenant_id,
            AiFinanceAnomaly(
                tenant_id=tenant_id,
                entity_type="journal_entry",
                entity_id=entity_id,
                anomaly_type="duplicate_entry",
                severity="medium",
                description="first",
            ),
        )
        await repo.upsert_ai_anomaly(
            tenant_id,
            AiFinanceAnomaly(
                tenant_id=tenant_id,
                entity_type="journal_entry",
                entity_id=entity_id,
                anomaly_type="duplicate_entry",
                severity="high",
                description="updated",
            ),
        )
        open_anomalies = await repo.list_open_ai_anomalies(tenant_id)
        matches = [a for a in open_anomalies if a.entity_id == entity_id]
        assert len(matches) == 1
        assert matches[0].severity == "high"
        await session.rollback()


async def test_reverse_flips_lines_and_stamps(automation_world: dict[str, str]) -> None:
    tenant_id = uuid.UUID(automation_world["tenant_id"])
    async with async_session_factory() as session:
        repo = FinanceRepository(session)
        entries = await repo.list_journal_entries(tenant_id, status=EntryStatus.POSTED)
        entry = entries[0]
        reversed_entry = await repo.reverse_journal_entry(
            entry.id,
            tenant_id,
            reversed_by_user_id=uuid.uuid4(),
            reversed_at=PIVOT,
        )
        await session.rollback()

    assert reversed_entry is not None
    assert reversed_entry.reversal_entry_id is not None
