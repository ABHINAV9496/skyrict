"""Multi-line order idempotency + concurrency (B1/B2/B3) — real Postgres.

Proves that a single order containing 2+ lines in the SAME warehouse
works correctly end-to-end (reserve / release / fulfil), and that a
concurrent duplicate-ref reservation can never inflate ``qty_reserved``
without a corresponding ledger row.

Skipped automatically when Postgres is unreachable (``migrated_schema``).
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from core.core.exceptions import MovementImmutableError
from core.db.session import async_session_factory, engine
from core.domain.entities import SalesOrderLine, StockMovement
from core.domain.value_objects import StockMovementType
from core.features.inventory.models.product import ErpProductModel
from core.features.inventory.models.warehouse import ErpWarehouseModel
from core.features.inventory.repository import InventoryRepository
from core.features.inventory.service import InventoryService
from core.models.tenant import TenantModel

pytestmark = pytest.mark.integration


class _NoopAuditService:
    async def log(self, **kwargs: object) -> None:
        return None


@pytest.fixture
async def multi_world(migrated_schema: None) -> dict[str, object]:
    """One tenant, two products, one warehouse, 10-unit receipt each."""
    tenant = uuid.uuid4()
    product_a = uuid.uuid4()
    product_b = uuid.uuid4()
    warehouse = uuid.uuid4()

    async with async_session_factory() as session:
        session.add(
            TenantModel(
                id=tenant,
                name="Multi-Line Tenant",
                slug=f"multi-{str(tenant)[:8]}",
                plan_tier="free",
                is_active=True,
            )
        )
        await session.commit()

    async with async_session_factory() as session:
        session.add_all(
            [
                ErpProductModel(
                    tenant_id=tenant,
                    id=product_a,
                    sku="SKU-A",
                    name="Widget A",
                ),
                ErpProductModel(
                    tenant_id=tenant,
                    id=product_b,
                    sku="SKU-B",
                    name="Widget B",
                ),
                ErpWarehouseModel(
                    tenant_id=tenant,
                    id=warehouse,
                    name="Main",
                ),
            ]
        )
        await session.flush()

        repo = InventoryRepository(session)
        for pid in (product_a, product_b):
            await repo.add_movement(
                StockMovement(
                    tenant_id=tenant,
                    product_id=pid,
                    warehouse_id=warehouse,
                    movement_type=StockMovementType.RECEIPT,
                    qty=Decimal("10"),
                    ref_type="po",
                    ref_id=f"PO-{str(pid)[:8]}",
                )
            )
        await session.commit()

    try:
        yield {
            "tenant": tenant,
            "product_a": product_a,
            "product_b": product_b,
            "warehouse": warehouse,
        }
    finally:
        async with async_session_factory() as session:
            for table in (
                "erp_stock_movements",
                "erp_stock_levels",
                "erp_products",
                "erp_warehouses",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tid"),
                    {"tid": tenant},
                )
            await session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant})
            await session.commit()
        await engine.dispose()


def _make_line(
    tenant_id: uuid.UUID, product_id: uuid.UUID, qty: Decimal
) -> SalesOrderLine:
    return SalesOrderLine(
        tenant_id=tenant_id,
        product_id=product_id,
        product_name="",
        sku="",
        quantity=qty,
    )


class TestMultiLineReserve:
    async def test_two_lines_same_warehouse_reserves_both_products(
        self, multi_world: dict[str, object]
    ) -> None:
        tenant: uuid.UUID = multi_world["tenant"]  # type: ignore[assignment]
        product_a: uuid.UUID = multi_world["product_a"]  # type: ignore[assignment]
        product_b: uuid.UUID = multi_world["product_b"]  # type: ignore[assignment]
        warehouse: uuid.UUID = multi_world["warehouse"]  # type: ignore[assignment]
        order_id = uuid.uuid4()
        lines = [
            _make_line(tenant, product_a, Decimal("3")),
            _make_line(tenant, product_b, Decimal("2")),
        ]

        async with async_session_factory() as session:
            service = InventoryService(InventoryRepository(session), _NoopAuditService())
            await service.reserve_order(
                tenant, warehouse_id=warehouse, order_id=order_id, lines=lines
            )

        async with async_session_factory() as session:
            repo = InventoryRepository(session)
            for pid, qty in [(product_a, "3"), (product_b, "2")]:
                level = await repo.get_stock_level(pid, warehouse, tenant)
                assert level is not None, f"Level missing for {pid}"
                assert level.qty_on_hand == Decimal("10")
                assert level.qty_reserved == Decimal(qty)

            movements = await repo.list_movements(tenant, warehouse_id=warehouse)
            ref_ids = [m.ref_id for m in movements]
            assert len([r for r in ref_ids if "reserve" in r]) == 2


class TestMultiLineFulfil:
    async def test_fulfil_writes_ledger_for_every_product(
        self, multi_world: dict[str, object]
    ) -> None:
        tenant: uuid.UUID = multi_world["tenant"]  # type: ignore[assignment]
        product_a: uuid.UUID = multi_world["product_a"]  # type: ignore[assignment]
        product_b: uuid.UUID = multi_world["product_b"]  # type: ignore[assignment]
        warehouse: uuid.UUID = multi_world["warehouse"]  # type: ignore[assignment]
        order_id = uuid.uuid4()
        lines = [
            _make_line(tenant, product_a, Decimal("3")),
            _make_line(tenant, product_b, Decimal("2")),
        ]

        async with async_session_factory() as session:
            service = InventoryService(InventoryRepository(session), _NoopAuditService())
            await service.reserve_order(
                tenant, warehouse_id=warehouse, order_id=order_id, lines=lines
            )

        async with async_session_factory() as session:
            service = InventoryService(InventoryRepository(session), _NoopAuditService())
            fulfil_lines = [
                _make_line(tenant, product_a, Decimal("3")),
                _make_line(tenant, product_b, Decimal("2")),
            ]
            result = await service.fulfil_order_lines(
                tenant, warehouse_id=warehouse, order_id=order_id, lines=fulfil_lines
            )
            assert len(result) == 2

        async with async_session_factory() as session:
            repo = InventoryRepository(session)
            for pid, out_qty in [(product_a, "3"), (product_b, "2")]:
                level = await repo.get_stock_level(pid, warehouse, tenant)
                assert level is not None
                assert level.qty_on_hand == Decimal("10") - Decimal(out_qty)
                assert level.qty_reserved == Decimal("0")

            movements = await repo.list_movements(tenant, warehouse_id=warehouse)
            ref_ids = [m.ref_id for m in movements]
            issue_refs = [r for r in ref_ids if "issue" in r]
            release_refs = [r for r in ref_ids if "release" in r]
            assert len(issue_refs) == 2
            assert len(release_refs) == 2


class TestMultiLineRelease:
    async def test_release_order_restores_reserved_to_zero(
        self, multi_world: dict[str, object]
    ) -> None:
        tenant: uuid.UUID = multi_world["tenant"]  # type: ignore[assignment]
        product_a: uuid.UUID = multi_world["product_a"]  # type: ignore[assignment]
        product_b: uuid.UUID = multi_world["product_b"]  # type: ignore[assignment]
        warehouse: uuid.UUID = multi_world["warehouse"]  # type: ignore[assignment]
        order_id = uuid.uuid4()
        lines = [
            _make_line(tenant, product_a, Decimal("4")),
            _make_line(tenant, product_b, Decimal("1")),
        ]

        async with async_session_factory() as session:
            service = InventoryService(InventoryRepository(session), _NoopAuditService())
            await service.reserve_order(
                tenant, warehouse_id=warehouse, order_id=order_id, lines=lines
            )

        async with async_session_factory() as session:
            service = InventoryService(InventoryRepository(session), _NoopAuditService())
            await service.release_order(
                tenant, warehouse_id=warehouse, order_id=order_id, lines=lines
            )

        async with async_session_factory() as session:
            repo = InventoryRepository(session)
            for pid in (product_a, product_b):
                level = await repo.get_stock_level(pid, warehouse, tenant)
                assert level is not None
                assert level.qty_reserved == Decimal("0")


class TestDuplicateRefConcurrency:
    async def test_same_ref_same_product_one_wins_one_rejects(
        self, multi_world: dict[str, object]
    ) -> None:
        tenant: uuid.UUID = multi_world["tenant"]  # type: ignore[assignment]
        product_a: uuid.UUID = multi_world["product_a"]  # type: ignore[assignment]
        warehouse: uuid.UUID = multi_world["warehouse"]  # type: ignore[assignment]
        shared_ref = f"SO-DUPLICATE-{uuid.uuid4()}"

        async def _reserve() -> str:
            async with async_session_factory() as session:
                service = InventoryService(InventoryRepository(session), _NoopAuditService())
                try:
                    await service.reserve_stock(
                        product_a,
                        warehouse,
                        Decimal("2"),
                        tenant,
                        ref_type="sale_order",
                        ref_id=shared_ref,
                    )
                    return "ok"
                except MovementImmutableError:
                    return "conflict"

        outcomes = await asyncio.gather(_reserve(), _reserve())
        assert sorted(outcomes) == ["conflict", "ok"]

        async with async_session_factory() as session:
            repo = InventoryRepository(session)
            level = await repo.get_stock_level(product_a, warehouse, tenant)
            assert level is not None
            assert level.qty_reserved == Decimal("2")

            reservations = await repo.list_movements(
                tenant,
                product_id=product_a,
                warehouse_id=warehouse,
                movement_type=StockMovementType.RESERVATION,
            )
            assert len(reservations) == 1
