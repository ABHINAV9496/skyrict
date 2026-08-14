"""Concurrent reservation integration tests — REAL Postgres, race-proof.

Proves the §5.4 capacity invariant (``qty_reserved <= qty_on_hand``) holds under
concurrency: two simultaneous ``reserve_stock`` calls racing for the same stock
level serialize on the row lock (``apply_reservation_qty``'s conditional
UPDATE), so exactly ONE can take the last units and the other fails with
``InsufficientStockError`` (409) — never a double-reservation or a CHECK
violation surfacing as an IntegrityError.

Each ``_reserve_once`` coroutine runs its own session on its own connection, so
the two transactions genuinely contend at the database. The suite skips when
Postgres is unavailable (see tests/integration/conftest.py).
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from core.core.exceptions import InsufficientStockError
from core.db.session import async_session_factory, engine
from core.domain.entities import StockMovement
from core.domain.value_objects import StockMovementType
from core.features.inventory.models.product import ErpProductModel
from core.features.inventory.models.warehouse import ErpWarehouseModel
from core.features.inventory.repository import InventoryRepository
from core.features.inventory.service import InventoryService
from core.models.tenant import TenantModel

pytestmark = pytest.mark.integration


class _NoopAuditService:
    """Duck-typed audit port — reservation calls never log, so a no-op suffices."""

    async def log(self, **kwargs: object) -> None:
        return None


@pytest.fixture
async def reservation_world(migrated_schema: None) -> dict[str, str]:
    """One tenant, product, warehouse, and a 5-unit receipt in the ledger.

    Async fixture: runs on the test's event loop like ``integration_db`` (a
    fresh world per test, since reservations from the previous test persist).
    """

    tenant = str(uuid.uuid4())
    product = str(uuid.uuid4())
    warehouse = str(uuid.uuid4())

    async with async_session_factory() as session:
        # Commit the tenant first: SQLAlchemy only orders cross-mapper
        # INSERTs through relationships(), so inserting tenants and
        # erp_products in one flush would attempt erp_products first.
        session.add(
            TenantModel(
                id=uuid.UUID(tenant),
                name="Reservation Tenant",
                slug=f"res-{tenant[:8]}",
                plan_tier="free",
                is_active=True,
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        session.add_all(
            [
                ErpProductModel(
                    tenant_id=uuid.UUID(tenant),
                    id=uuid.UUID(product),
                    sku="SKU-CONCURRENT",
                    name="Contended Widget",
                ),
                ErpWarehouseModel(
                    tenant_id=uuid.UUID(tenant),
                    id=uuid.UUID(warehouse),
                    name="Main",
                ),
            ]
        )
        await session.flush()

        repo = InventoryRepository(session)
        await repo.add_movement(
            StockMovement(
                tenant_id=uuid.UUID(tenant),
                product_id=uuid.UUID(product),
                warehouse_id=uuid.UUID(warehouse),
                movement_type=StockMovementType.RECEIPT,
                qty=Decimal("5"),
                ref_type="po",
                ref_id="PO-CONCURRENT",
            )
        )
        await session.commit()

    try:
        yield {"tenant": tenant, "product": product, "warehouse": warehouse}
    finally:
        async with async_session_factory() as session:
            tid = uuid.UUID(tenant)
            for table in (
                "erp_stock_movements",
                "erp_stock_levels",
                "erp_products",
                "erp_warehouses",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tid}
                )
            await session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
            await session.commit()
        # pytest-asyncio gives every test its own event loop; drop pooled
        # connections so the next test cannot reuse one bound to a closed loop.
        await engine.dispose()


def _u(value: str) -> uuid.UUID:
    return uuid.UUID(value)


async def _reserve_once(
    tenant: uuid.UUID,
    product: uuid.UUID,
    warehouse: uuid.UUID,
    qty: Decimal,
    ref_id: str,
) -> str:
    """Run one reservation in its own session/connection; return the outcome."""
    async with async_session_factory() as session:
        service = InventoryService(InventoryRepository(session), _NoopAuditService())
        try:
            await service.reserve_stock(product, warehouse, qty, tenant, ref_id=ref_id)
            return "ok"
        except InsufficientStockError:
            return "insufficient"


class TestReservationConcurrency:
    async def test_concurrent_over_capacity_reserves_reject_exactly_one(
        self, reservation_world: dict[str, str]
    ) -> None:
        tenant = _u(reservation_world["tenant"])
        product = _u(reservation_world["product"])
        warehouse = _u(reservation_world["warehouse"])

        outcomes = await asyncio.gather(
            _reserve_once(tenant, product, warehouse, Decimal("4"), "SO-CONC-A"),
            _reserve_once(tenant, product, warehouse, Decimal("4"), "SO-CONC-B"),
        )

        assert sorted(outcomes) == ["insufficient", "ok"]

        async with async_session_factory() as session:
            repo = InventoryRepository(session)
            level = await repo.get_stock_level(product, warehouse, tenant)
            assert level is not None
            assert level.qty_on_hand == Decimal("5")
            assert level.qty_reserved == Decimal("4")

            reservations = await repo.list_movements(
                tenant,
                product_id=product,
                warehouse_id=warehouse,
                movement_type=StockMovementType.RESERVATION,
            )
            assert len(reservations) == 1

    async def test_concurrent_reservations_within_capacity_both_succeed(
        self, reservation_world: dict[str, str]
    ) -> None:
        tenant = _u(reservation_world["tenant"])
        product = _u(reservation_world["product"])
        warehouse = _u(reservation_world["warehouse"])

        outcomes = await asyncio.gather(
            _reserve_once(tenant, product, warehouse, Decimal("2"), "SO-CONC-C"),
            _reserve_once(tenant, product, warehouse, Decimal("3"), "SO-CONC-D"),
        )

        assert sorted(outcomes) == ["ok", "ok"]

        async with async_session_factory() as session:
            repo = InventoryRepository(session)
            level = await repo.get_stock_level(product, warehouse, tenant)
            assert level is not None
            assert level.qty_on_hand == Decimal("5")
            assert level.qty_reserved == Decimal("5")
