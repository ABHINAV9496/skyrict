"""Finance document-numbering regression tests — verified against REAL Postgres.

``next_invoice_number`` / ``next_payment_number`` call ``nextval()`` on the
migration-0004 sequences. The sequence name MUST be passed as a quoted string
literal (``nextval('seq_erp_invoice_number')``) so Postgres coerces it to a
``regclass`` — a bare identifier is parsed as a *column* reference and fails
with ``UndefinedColumnError`` (regression: masked 500 on invoice/payment
create).

Sequence state persists across runs, so these tests assert the returned
format and the relative increment, never absolute values.
"""

from __future__ import annotations

import asyncio
import re
import uuid

import pytest
from sqlalchemy import text

from core.db.session import async_session_factory, engine
from core.features.finance.repository import FinanceRepository
from core.models.tenant import TenantModel

pytestmark = pytest.mark.integration

INVOICE_NUMBER_RE = re.compile(r"^INV-\d{4}-\d{5}$")
PAYMENT_NUMBER_RE = re.compile(r"^PMT-\d{4}-\d{5}$")


@pytest.fixture(scope="module")
def numbering_world(migrated_schema: None) -> dict[str, str]:
    """Seed one tenant so numbering runs in a realistic tenant context.

    Plain (sync) fixture: all DB work runs inside one ``asyncio.run()`` and the
    engine pool is disposed before that run's loop closes, so the function-
    scoped async tests that follow get a clean pool bound to their own loops.
    """

    tenant_id = str(uuid.uuid4())

    async def _setup() -> str:
        async with async_session_factory() as session:
            session.add(
                TenantModel(
                    id=uuid.UUID(tenant_id),
                    name="Numbering Tenant",
                    slug=f"num-{tenant_id[:8]}",
                    plan_tier="free",
                    is_active=True,
                )
            )
            await session.commit()
            await engine.dispose()
        return tenant_id

    async def _teardown() -> None:
        async with async_session_factory() as session:
            await session.execute(
                text("DELETE FROM tenants WHERE id = :tid"), {"tid": uuid.UUID(tenant_id)}
            )
            await session.commit()
            await engine.dispose()

    created = asyncio.run(_setup())
    try:
        yield {"tenant_id": created}
    finally:
        asyncio.run(_teardown())


def _sequence_suffix(number: str) -> int:
    return int(number.rsplit("-", 1)[1])


async def test_invoice_number_format_and_increment(numbering_world: dict[str, str]) -> None:
    async with async_session_factory() as session:
        repo = FinanceRepository(session)
        first = await repo.next_invoice_number(uuid.UUID(numbering_world["tenant_id"]), 2026)
        second = await repo.next_invoice_number(uuid.UUID(numbering_world["tenant_id"]), 2026)
        await session.rollback()

    assert INVOICE_NUMBER_RE.match(first)
    assert _sequence_suffix(second) == _sequence_suffix(first) + 1


async def test_payment_number_format_and_increment(numbering_world: dict[str, str]) -> None:
    async with async_session_factory() as session:
        repo = FinanceRepository(session)
        first = await repo.next_payment_number(uuid.UUID(numbering_world["tenant_id"]), 2026)
        second = await repo.next_payment_number(uuid.UUID(numbering_world["tenant_id"]), 2026)
        await session.rollback()

    assert PAYMENT_NUMBER_RE.match(first)
    assert _sequence_suffix(second) == _sequence_suffix(first) + 1
