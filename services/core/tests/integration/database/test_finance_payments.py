"""Payment ledger path integration (SKY-96): H1/H2/H3 over REAL Postgres.

``apply_payment`` must book money exactly once and post its receipt leg to the
ledger:

  - H2: applying a payment posts a balanced JE (DR Cash 1200 / CR AR 1100)
    stamped ``(source='payment', source_ref=payment_id)``;
  - H3: manual payments get a deterministic ``(source, source_ref)`` so a
    replayed request returns the existing payment instead of double-booking;
  - undo (``delete_payment``) removes the payment's JE with it - journal lines
    RESTRICT on the entry FK, so lines are deleted before the entry.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from core.core.constants import AR_ACCOUNT_CODE, CASH_ACCOUNT_CODE
from core.db.session import async_session_factory, engine
from core.domain.value_objects import AccountType, EntryStatus, InvoiceStatus
from core.features.finance.models.chart_of_account import ErpChartOfAccountModel
from core.features.finance.models.invoice import ErpInvoiceModel
from core.features.finance.models.journal_entry import ErpJournalEntryModel
from core.features.finance.models.journal_line import ErpJournalLineModel
from core.features.finance.models.payment import ErpPaymentModel
from core.features.finance.repository import FinanceRepository
from core.features.finance.service import FinanceService
from core.models.tenant import TenantModel

pytestmark = pytest.mark.integration


class _NoopAudit:
    async def log(self, **kwargs) -> None:
        return None


class _NoopEvents:
    def journal_entry_posted(self, **kwargs) -> None:
        return None

    def invoice_created(self, **kwargs) -> None:
        return None

    def invoice_approved(self, **kwargs) -> None:
        return None

    def payment_applied(self, **kwargs) -> None:
        return None


@pytest.fixture(scope="module")
def payment_world(migrated_schema: None) -> dict[str, str]:
    """Fresh tenant + chart accounts + one approved invoice."""

    async def _setup() -> dict[str, str]:
        tenant_id = uuid.uuid4()
        async with async_session_factory() as session:
            session.add(
                TenantModel(
                    id=tenant_id,
                    name="Payment Tenant",
                    slug=f"pay-{tenant_id.hex[:8]}",
                    plan_tier="free",
                    is_active=True,
                )
            )
            await session.flush()
            for code, name, acct_type in [
                (AR_ACCOUNT_CODE, "Accounts Receivable", AccountType.ASSET),
                (CASH_ACCOUNT_CODE, "Cash", AccountType.ASSET),
            ]:
                session.add(
                    ErpChartOfAccountModel(
                        tenant_id=tenant_id, code=code, name=name, account_type=acct_type
                    )
                )
            invoice = ErpInvoiceModel(
                tenant_id=tenant_id,
                invoice_number="PAY-TEST-1",
                customer_id=uuid.uuid4(),
                invoice_date=date(2026, 3, 1),
                due_date=date(2026, 4, 1),
                status=InvoiceStatus.APPROVED,
                total=Decimal("300"),
                source="manual",
                source_ref=None,
            )
            session.add(invoice)
            await session.flush()
            invoice_id = str(invoice.id)
            await session.commit()
            await engine.dispose()
        return {"tenant_id": str(tenant_id), "invoice_id": invoice_id}

    async def _teardown() -> None:
        async with async_session_factory() as session:
            await session.execute(
                text("DELETE FROM erp_payments WHERE tenant_id = :tid"),
                {"tid": uuid.UUID(payment_world["tenant_id"])},
            )
            await session.execute(
                text("DELETE FROM tenants WHERE id = :tid"),
                {"tid": uuid.UUID(payment_world["tenant_id"])},
            )
            await session.commit()
            await engine.dispose()

    payment_world = asyncio.run(_setup())
    try:
        yield payment_world
    finally:
        asyncio.run(_teardown())


@pytest.fixture(autouse=True)
async def clean_payments(payment_world: dict[str, str]) -> None:
    """Each test owns clean payment + ledger state for the tenant."""
    tenant_id = uuid.UUID(payment_world["tenant_id"])
    async with async_session_factory() as session:
        await session.execute(
            text("DELETE FROM erp_payments WHERE tenant_id = :tid"), {"tid": tenant_id}
        )
        await session.execute(
            text("DELETE FROM erp_journal_lines WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await session.execute(
            text("DELETE FROM erp_journal_entries WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await session.execute(
            text("UPDATE erp_invoices SET status = 'approved' WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        await session.commit()
    yield


def _service(session) -> FinanceService:
    return FinanceService(
        repo=FinanceRepository(session),
        audit=_NoopAudit(),
        events=_NoopEvents(),
    )


async def test_apply_payment_posts_balanced_receipt_leg(
    payment_world: dict[str, str],
) -> None:
    tenant_id = uuid.UUID(payment_world["tenant_id"])
    invoice_id = uuid.UUID(payment_world["invoice_id"])

    async with async_session_factory() as session:
        svc = _service(session)
        created = await svc.apply_payment(
            tenant_id=tenant_id,
            user_id=uuid.uuid4(),
            invoice_id=invoice_id,
            amount=Decimal("100"),
            method="card",
            paid_at=datetime(2026, 3, 5, 9, 0, 0, tzinfo=UTC),
        )
        await session.commit()
        payment_id = created.id
        assert payment_id is not None

        entry = (
            await session.execute(
                select(ErpJournalEntryModel).where(
                    ErpJournalEntryModel.tenant_id == tenant_id,
                    ErpJournalEntryModel.source == "payment",
                    ErpJournalEntryModel.source_ref == str(payment_id),
                )
            )
        ).scalar_one_or_none()
        assert entry is not None, "apply_payment must post its receipt leg to the ledger"
        assert entry.status == EntryStatus.POSTED

        lines = list(
            (
                await session.execute(
                    select(ErpJournalLineModel).where(
                        ErpJournalLineModel.tenant_id == tenant_id,
                        ErpJournalLineModel.entry_id == entry.id,
                    )
                )
            ).scalars()
        )
        assert len(lines) == 2
        debit_total = sum((line.debit or Decimal("0")) for line in lines)
        credit_total = sum((line.credit or Decimal("0")) for line in lines)
        assert debit_total == Decimal("100")
        assert debit_total == credit_total, "receipt leg must be balanced"

        invoice_status = await session.scalar(
            select(ErpInvoiceModel.status).where(
                ErpInvoiceModel.tenant_id == tenant_id,
                ErpInvoiceModel.id == invoice_id,
            )
        )
        assert invoice_status == InvoiceStatus.APPROVED  # partial payment only


async def test_replayed_payment_does_not_double_book(
    payment_world: dict[str, str],
) -> None:
    tenant_id = uuid.UUID(payment_world["tenant_id"])
    invoice_id = uuid.UUID(payment_world["invoice_id"])

    async with async_session_factory() as session:
        svc = _service(session)
        first = await svc.apply_payment(
            tenant_id=tenant_id,
            user_id=uuid.uuid4(),
            invoice_id=invoice_id,
            amount=Decimal("300"),
            method="bank",
            paid_at=datetime(2026, 3, 5, 9, 0, 0, tzinfo=UTC),
        )
        await session.commit()
        first_id = str(first.id)

        replay = await svc.apply_payment(
            tenant_id=tenant_id,
            user_id=uuid.uuid4(),
            invoice_id=invoice_id,
            amount=Decimal("300"),
            method="bank",
            paid_at=datetime(2026, 3, 5, 9, 0, 0, tzinfo=UTC),
        )
        await session.commit()

        payments = list(
            (
                await session.execute(
                    select(ErpPaymentModel).where(
                        ErpPaymentModel.tenant_id == tenant_id,
                        ErpPaymentModel.invoice_id == invoice_id,
                    )
                )
            ).scalars()
        )
        assert len(payments) == 1
        assert str(payments[0].id) == first_id
        assert replay.id == payments[0].id

        entry_count = await session.scalar(
            select(func.count())
            .select_from(ErpJournalEntryModel)
            .where(
                ErpJournalEntryModel.tenant_id == tenant_id,
                ErpJournalEntryModel.source == "payment",
            )
        )
        assert entry_count == 1, "replay must not post a second receipt leg"

        invoice_status = await session.scalar(
            select(ErpInvoiceModel.status).where(
                ErpInvoiceModel.tenant_id == tenant_id,
                ErpInvoiceModel.id == invoice_id,
            )
        )
        assert invoice_status == InvoiceStatus.PAID


async def test_delete_payment_removes_receipt_leg(
    payment_world: dict[str, str],
) -> None:
    tenant_id = uuid.UUID(payment_world["tenant_id"])
    invoice_id = uuid.UUID(payment_world["invoice_id"])

    async with async_session_factory() as session:
        svc = _service(session)
        created = await svc.apply_payment(
            tenant_id=tenant_id,
            user_id=uuid.uuid4(),
            invoice_id=invoice_id,
            amount=Decimal("100"),
            method="card",
            paid_at=datetime(2026, 3, 5, 9, 0, 0, tzinfo=UTC),
        )
        await session.commit()
        payment_id = created.id
        assert payment_id is not None

        repo = FinanceRepository(session)
        deleted = await repo.delete_payment(payment_id, tenant_id)
        await session.commit()
        assert deleted

        entry = (
            await session.execute(
                select(ErpJournalEntryModel).where(
                    ErpJournalEntryModel.tenant_id == tenant_id,
                    ErpJournalEntryModel.source == "payment",
                    ErpJournalEntryModel.source_ref == str(payment_id),
                )
            )
        ).scalar_one_or_none()
        assert entry is None, "deleting the payment must delete its receipt leg"

        reserve = await repo.sum_payments_for_invoice(invoice_id, tenant_id)
        assert reserve == Decimal("0")
