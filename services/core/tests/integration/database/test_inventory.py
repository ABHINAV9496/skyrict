"""Inventory data-layer integration tests — real Postgres, migrated schema.

Covers the INV-DATA-001 acceptance criteria at both layers:

  - SQL level: CHECK/UNIQUE/composite-FK constraints bite regardless of
    application code; RLS keeps tenant B blind to tenant A's rows; a
    cross-tenant stock level is rejected by the composite FK even as the
    table OWNER (referential integrity agrees with RLS).
  - Repository level: add_movement + recompute semantics, per-warehouse
    isolation, idempotency, two-tenant scoping, soft delete.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from core.db.session import async_session_factory, engine
from core.domain.entities import Product, StockMovement
from core.domain.value_objects import StockMovementType
from core.features.inventory.models.product import ErpProductModel
from core.features.inventory.models.warehouse import ErpWarehouseModel
from core.features.inventory.repository import InventoryRepository
from core.models.tenant import TenantModel
from tests.integration.database.test_rls import RLS_ROLE, _ensure_rls_role

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def inventory_world(migrated_schema: None) -> dict[str, str]:
    """Seed two tenants with products/warehouses; no movements or levels yet.

    Plain (sync) fixture: all DB work runs inside one ``asyncio.run()`` and the
    engine pool is disposed before that run's loop closes (conftest convention).
    """

    async def _setup() -> dict[str, str]:
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        wh_a1 = str(uuid.uuid4())
        wh_a2 = str(uuid.uuid4())
        wh_a3 = str(uuid.uuid4())
        wh_a4 = str(uuid.uuid4())
        wh_a5 = str(uuid.uuid4())
        wh_a6 = str(uuid.uuid4())
        wh_a7 = str(uuid.uuid4())
        wh_b = str(uuid.uuid4())
        product_a = str(uuid.uuid4())
        product_b = str(uuid.uuid4())

        async with async_session_factory() as session:
            session.add_all(
                [
                    TenantModel(
                        id=uuid.UUID(tenant_a),
                        name="Inventory Tenant A",
                        slug=f"inv-a-{tenant_a[:8]}",
                        plan_tier="free",
                        is_active=True,
                    ),
                    TenantModel(
                        id=uuid.UUID(tenant_b),
                        name="Inventory Tenant B",
                        slug=f"inv-b-{tenant_b[:8]}",
                        plan_tier="free",
                        is_active=True,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    ErpWarehouseModel(
                        tenant_id=uuid.UUID(tenant_a), id=uuid.UUID(wh_a1), name="Main"
                    ),
                    ErpWarehouseModel(
                        tenant_id=uuid.UUID(tenant_a), id=uuid.UUID(wh_a2), name="Secondary"
                    ),
                    ErpWarehouseModel(
                        tenant_id=uuid.UUID(tenant_a), id=uuid.UUID(wh_a3), name="Ledger 1"
                    ),
                    ErpWarehouseModel(
                        tenant_id=uuid.UUID(tenant_a), id=uuid.UUID(wh_a4), name="Ledger 2"
                    ),
                    ErpWarehouseModel(
                        tenant_id=uuid.UUID(tenant_a), id=uuid.UUID(wh_a5), name="Ledger 3"
                    ),
                    ErpWarehouseModel(
                        tenant_id=uuid.UUID(tenant_a), id=uuid.UUID(wh_a6), name="Ledger 4"
                    ),
                    ErpWarehouseModel(
                        tenant_id=uuid.UUID(tenant_a), id=uuid.UUID(wh_a7), name="Ledger 5"
                    ),
                    ErpWarehouseModel(
                        tenant_id=uuid.UUID(tenant_b), id=uuid.UUID(wh_b), name="Main"
                    ),
                    ErpProductModel(
                        tenant_id=uuid.UUID(tenant_a),
                        id=uuid.UUID(product_a),
                        sku="SKU-A",
                        name="Widget A",
                    ),
                    ErpProductModel(
                        tenant_id=uuid.UUID(tenant_b),
                        id=uuid.UUID(product_b),
                        sku="SKU-B",
                        name="Widget B",
                    ),
                ]
            )
            await session.commit()
            await engine.dispose()

        return {
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "wh_a1": wh_a1,
            "wh_a2": wh_a2,
            "wh_a3": wh_a3,
            "wh_a4": wh_a4,
            "wh_a5": wh_a5,
            "wh_a6": wh_a6,
            "wh_a7": wh_a7,
            "wh_b": wh_b,
            "product_a": product_a,
            "product_b": product_b,
        }

    async def _teardown() -> None:
        async with async_session_factory() as session:
            for tid in (inventory_world_data["tenant_a"], inventory_world_data["tenant_b"]):
                tid_uuid = uuid.UUID(tid)
                for table in (
                    "erp_stock_movements",
                    "erp_stock_levels",
                    "erp_products",
                    "erp_warehouses",
                ):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tid_uuid}
                    )
                await session.execute(
                    text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid_uuid}
                )
            await session.commit()
            await engine.dispose()

    inventory_world_data = asyncio.run(_setup())
    try:
        yield inventory_world_data
    finally:
        asyncio.run(_teardown())


def _u(value: str) -> uuid.UUID:
    return uuid.UUID(value)


class TestInventoryConstraints:
    """DB-level invariant tests — run as owner, so only constraints bite."""

    async def test_negative_on_hand_rejected(self, inventory_world: dict[str, str]) -> None:
        async with engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_stock_levels "
                        "(tenant_id, id, product_id, warehouse_id, qty_on_hand) "
                        "VALUES (:t, gen_random_uuid(), :p, :w, -1)"
                    ),
                    {
                        "t": _u(inventory_world["tenant_a"]),
                        "p": _u(inventory_world["product_a"]),
                        "w": _u(inventory_world["wh_a1"]),
                    },
                )
            assert "ck_erp_stock_levels_on_hand_non_negative" in str(excinfo.value)
        await engine.dispose()

    async def test_reserved_exceeding_on_hand_rejected(
        self, inventory_world: dict[str, str]
    ) -> None:
        async with engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_stock_levels "
                        "(tenant_id, id, product_id, warehouse_id, qty_on_hand, qty_reserved) "
                        "VALUES (:t, gen_random_uuid(), :p, :w, 5, 6)"
                    ),
                    {
                        "t": _u(inventory_world["tenant_a"]),
                        "p": _u(inventory_world["product_a"]),
                        "w": _u(inventory_world["wh_a1"]),
                    },
                )
            assert "ck_erp_stock_levels_reserved_range" in str(excinfo.value)
        await engine.dispose()

    async def test_negative_reserved_rejected(self, inventory_world: dict[str, str]) -> None:
        async with engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_stock_levels "
                        "(tenant_id, id, product_id, warehouse_id, qty_reserved) "
                        "VALUES (:t, gen_random_uuid(), :p, :w, -1)"
                    ),
                    {
                        "t": _u(inventory_world["tenant_a"]),
                        "p": _u(inventory_world["product_a"]),
                        "w": _u(inventory_world["wh_a1"]),
                    },
                )
            assert "ck_erp_stock_levels_reserved_range" in str(excinfo.value)
        await engine.dispose()

    async def test_zero_qty_movement_rejected(self, inventory_world: dict[str, str]) -> None:
        async with engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_stock_movements "
                        "(tenant_id, id, product_id, warehouse_id, movement_type, qty, ref_type, ref_id) "
                        "VALUES (:t, gen_random_uuid(), :p, :w, 'receipt', 0, 'po', 'PO-ZERO')"
                    ),
                    {
                        "t": _u(inventory_world["tenant_a"]),
                        "p": _u(inventory_world["product_a"]),
                        "w": _u(inventory_world["wh_a1"]),
                    },
                )
            assert "ck_erp_stock_movements_qty_nonzero" in str(excinfo.value)
        await engine.dispose()

    async def test_duplicate_sku_rejected(self, inventory_world: dict[str, str]) -> None:
        async with engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_products (tenant_id, id, sku, name) "
                        "VALUES (:t, gen_random_uuid(), 'SKU-A', 'Dup')"
                    ),
                    {"t": _u(inventory_world["tenant_a"])},
                )
            assert "uq_erp_products_tenant_sku" in str(excinfo.value)
        await engine.dispose()

    async def test_duplicate_stock_level_rejected(self, inventory_world: dict[str, str]) -> None:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "INSERT INTO erp_stock_levels "
                    "(tenant_id, id, product_id, warehouse_id) "
                    "VALUES (:t, gen_random_uuid(), :p, :w)"
                ),
                {
                    "t": _u(inventory_world["tenant_a"]),
                    "p": _u(inventory_world["product_a"]),
                    "w": _u(inventory_world["wh_a1"]),
                },
            )
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_stock_levels "
                        "(tenant_id, id, product_id, warehouse_id) "
                        "VALUES (:t, gen_random_uuid(), :p, :w)"
                    ),
                    {
                        "t": _u(inventory_world["tenant_a"]),
                        "p": _u(inventory_world["product_a"]),
                        "w": _u(inventory_world["wh_a1"]),
                    },
                )
            assert "uq_erp_stock_levels_product_warehouse" in str(excinfo.value)
        await engine.dispose()


class TestInventoryRls:
    async def test_tenant_b_cannot_read_tenant_a_rows(
        self, inventory_world: dict[str, str]
    ) -> None:
        await _ensure_rls_role()
        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET ROLE {RLS_ROLE}")

            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (inventory_world["tenant_a"],),
            )
            a_skus = (await conn.execute(text("SELECT sku FROM erp_products"))).scalars().all()
            assert [str(sku) for sku in a_skus] == ["SKU-A"]

            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (inventory_world["tenant_b"],),
            )
            b_skus = (await conn.execute(text("SELECT sku FROM erp_products"))).scalars().all()
            assert [str(sku) for sku in b_skus] == ["SKU-B"]
            assert "SKU-A" not in b_skus

            await conn.exec_driver_sql("RESET ROLE")
        await engine.dispose()

    async def test_cross_tenant_insert_blocked_by_rls(
        self, inventory_world: dict[str, str]
    ) -> None:
        await _ensure_rls_role()
        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET ROLE {RLS_ROLE}")
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (inventory_world["tenant_a"],),
            )
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_products (tenant_id, id, sku, name) "
                        "VALUES (:t, gen_random_uuid(), 'SNEAKY', 'X')"
                    ),
                    {"t": _u(inventory_world["tenant_b"])},
                )
            assert "row-level security" in str(excinfo.value).lower()
            await conn.exec_driver_sql("RESET ROLE")
        await engine.dispose()

    async def test_cross_tenant_stock_level_rejected_by_composite_fk(
        self, inventory_world: dict[str, str]
    ) -> None:
        # The owner bypasses RLS, so ONLY the composite FK can stop
        # (tenant_b, product_a) -> erp_products(tenant_b, id): product_a is a
        # tenant-A row, so the composite key doesn't exist in tenant B.
        async with engine.connect() as conn:
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_stock_levels "
                        "(tenant_id, id, product_id, warehouse_id) "
                        "VALUES (:t, gen_random_uuid(), :p, :w)"
                    ),
                    {
                        "t": _u(inventory_world["tenant_b"]),
                        "p": _u(inventory_world["product_a"]),
                        "w": _u(inventory_world["wh_b"]),
                    },
                )
            assert "fk_erp_stock_levels_product_tenant" in str(excinfo.value)
        await engine.dispose()

    async def test_movements_have_no_updated_at_column(self, migrated_schema: None) -> None:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'erp_stock_movements' AND column_name = 'updated_at'"
                )
            )
            assert result.scalar_one_or_none() is None
        await engine.dispose()


class TestPerWarehouseIsolation:
    async def test_movements_in_one_warehouse_do_not_touch_another(
        self, inventory_world: dict[str, str]
    ) -> None:
        tenant = _u(inventory_world["tenant_a"])
        product = _u(inventory_world["product_a"])
        wh1 = _u(inventory_world["wh_a1"])
        wh2 = _u(inventory_world["wh_a2"])

        async with async_session_factory() as session:
            repo = InventoryRepository(session)

            assert await repo.get_stock_level(product, wh1, tenant) is None

            await repo.add_movement(
                StockMovement(
                    tenant_id=tenant,
                    product_id=product,
                    warehouse_id=wh2,
                    movement_type=StockMovementType.RECEIPT,
                    qty=Decimal("5"),
                    ref_type="po",
                    ref_id="PO-WH2-ISOLATION",
                )
            )
            await session.commit()

            assert await repo.get_stock_level(product, wh1, tenant) is None
            level = await repo.get_stock_level(product, wh2, tenant)
            assert level is not None
            assert level.qty_on_hand == Decimal("5")
            assert level.qty_reserved == Decimal("0")


class TestMovementLedger:
    async def test_add_movement_and_recompute(self, inventory_world: dict[str, str]) -> None:
        tenant = _u(inventory_world["tenant_a"])
        product = _u(inventory_world["product_a"])
        wh1 = _u(inventory_world["wh_a1"])

        async with async_session_factory() as session:
            repo = InventoryRepository(session)
            await repo.add_movement(
                StockMovement(
                    tenant,
                    product,
                    wh1,
                    StockMovementType.RECEIPT,
                    Decimal("10"),
                    "po",
                    "PO-LEDGER-1",
                )
            )
            await repo.add_movement(
                StockMovement(
                    tenant,
                    product,
                    wh1,
                    StockMovementType.ISSUE,
                    Decimal("-4"),
                    "so",
                    "SO-LEDGER-1",
                )
            )
            await repo.add_movement(
                StockMovement(
                    tenant,
                    product,
                    wh1,
                    StockMovementType.RESERVATION,
                    Decimal("2"),
                    "so",
                    "SO-RESERVE-1",
                )
            )
            await session.commit()

            level = await repo.get_stock_level(product, wh1, tenant)
            assert level is not None
            assert level.qty_on_hand == Decimal("6")
            assert level.qty_reserved == Decimal("2")

    async def test_release_lowers_reserved(self, inventory_world: dict[str, str]) -> None:
        # Self-contained on a dedicated warehouse: receipt + reservation + release.
        tenant = _u(inventory_world["tenant_a"])
        product = _u(inventory_world["product_a"])
        wh1 = _u(inventory_world["wh_a3"])

        async with async_session_factory() as session:
            repo = InventoryRepository(session)
            await repo.add_movement(
                StockMovement(
                    tenant,
                    product,
                    wh1,
                    StockMovementType.RECEIPT,
                    Decimal("6"),
                    "po",
                    "PO-RELEASE-1",
                )
            )
            await repo.add_movement(
                StockMovement(
                    tenant,
                    product,
                    wh1,
                    StockMovementType.RESERVATION,
                    Decimal("2"),
                    "so",
                    "SO-RELEASE-1",
                )
            )
            await repo.add_movement(
                StockMovement(
                    tenant,
                    product,
                    wh1,
                    StockMovementType.RELEASE,
                    Decimal("-2"),
                    "so",
                    "SO-RELEASE-1-CANCEL",
                )
            )
            await session.commit()

            level = await repo.get_stock_level(product, wh1, tenant)
            assert level is not None
            assert level.qty_on_hand == Decimal("6")
            assert level.qty_reserved == Decimal("0")

    async def test_transfer_is_dual_row_sharing_one_ref(
        self, inventory_world: dict[str, str]
    ) -> None:
        tenant = _u(inventory_world["tenant_a"])
        product = _u(inventory_world["product_a"])
        wh1 = _u(inventory_world["wh_a4"])
        wh2 = _u(inventory_world["wh_a5"])

        async with async_session_factory() as session:
            repo = InventoryRepository(session)
            await repo.add_movement(
                StockMovement(
                    tenant,
                    product,
                    wh1,
                    StockMovementType.RECEIPT,
                    Decimal("3"),
                    "po",
                    "PO-TRANSFER-1",
                )
            )
            await repo.add_movement(
                StockMovement(
                    tenant,
                    product,
                    wh1,
                    StockMovementType.TRANSFER,
                    Decimal("-3"),
                    "transfer",
                    "TR-LEDGER-1",
                )
            )
            await repo.add_movement(
                StockMovement(
                    tenant,
                    product,
                    wh2,
                    StockMovementType.TRANSFER,
                    Decimal("3"),
                    "transfer",
                    "TR-LEDGER-1",
                )
            )
            await session.commit()

            src = await repo.get_stock_level(product, wh1, tenant)
            dst = await repo.get_stock_level(product, wh2, tenant)
            assert src is not None and src.qty_on_hand == Decimal("0")
            assert dst is not None and dst.qty_on_hand == Decimal("3")

            movements = await repo.list_movements(product, wh1, tenant)
            assert [m.ref_id for m in movements].count("TR-LEDGER-1") == 1

    async def test_idempotency_returns_existing_movement(
        self, inventory_world: dict[str, str]
    ) -> None:
        tenant = _u(inventory_world["tenant_a"])
        product = _u(inventory_world["product_a"])
        wh1 = _u(inventory_world["wh_a1"])

        async with async_session_factory() as session:
            repo = InventoryRepository(session)
            first = await repo.add_movement(
                StockMovement(
                    tenant,
                    product,
                    wh1,
                    StockMovementType.RECEIPT,
                    Decimal("2"),
                    "po",
                    "PO-IDEMPOTENT",
                )
            )
            second = await repo.add_movement(
                StockMovement(
                    tenant,
                    product,
                    wh1,
                    StockMovementType.RECEIPT,
                    Decimal("2"),
                    "po",
                    "PO-IDEMPOTENT",
                )
            )
            await session.commit()

            assert second.id == first.id
            movements = await repo.list_movements(product, wh1, tenant)
            assert [m.ref_id for m in movements].count("PO-IDEMPOTENT") == 1

    async def test_over_reservation_rejected_and_movement_rolled_back(
        self, inventory_world: dict[str, str]
    ) -> None:
        # Fresh warehouse: on_hand 0. Reserving 5 must fail the DB CHECK and
        # roll back BOTH the materialized row AND the ledger insert.
        tenant = _u(inventory_world["tenant_a"])
        product = _u(inventory_world["product_a"])
        wh2 = _u(inventory_world["wh_a6"])

        async with async_session_factory() as session:
            repo = InventoryRepository(session)
            with pytest.raises(IntegrityError) as excinfo:
                await repo.add_movement(
                    StockMovement(
                        tenant,
                        product,
                        wh2,
                        StockMovementType.RESERVATION,
                        Decimal("5"),
                        "so",
                        "SO-OVERRESERVE",
                    )
                )
            assert "ck_erp_stock_levels_reserved_range" in str(excinfo.value)

            await session.rollback()
            assert await repo.get_movement_by_ref("so", "SO-OVERRESERVE", wh2, tenant) is None
            assert await repo.get_stock_level(product, wh2, tenant) is None


class TestRecomputeAfterDrift:
    async def test_recompute_rebuilds_level_from_ledger(
        self, inventory_world: dict[str, str]
    ) -> None:
        # Simulate drift: write a ledger row past the repository, then rebuild.
        tenant = _u(inventory_world["tenant_a"])
        product = _u(inventory_world["product_a"])
        wh2 = _u(inventory_world["wh_a7"])

        async with async_session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO erp_stock_movements "
                    "(tenant_id, id, product_id, warehouse_id, movement_type, qty, ref_type, ref_id) "
                    "VALUES (:t, gen_random_uuid(), :p, :w, 'adjustment', :q, 'drift', :rid)"
                ),
                {
                    "t": tenant,
                    "p": product,
                    "w": wh2,
                    "q": Decimal("7"),
                    "rid": "DRIFT-1",
                },
            )
            repo = InventoryRepository(session)
            level = await repo.recompute_stock_level(product, wh2, tenant)
            assert level.qty_on_hand == Decimal("7")
            assert level.qty_reserved == Decimal("0")
            await session.commit()


class TestRepositoryIsolation:
    async def test_tenant_b_cannot_read_tenant_a_through_repository(
        self, inventory_world: dict[str, str]
    ) -> None:
        async with async_session_factory() as session:
            repo = InventoryRepository(session)
            product_b_view = await repo.get_product(
                _u(inventory_world["product_a"]), _u(inventory_world["tenant_b"])
            )
            warehouse_b_view = await repo.get_warehouse(
                _u(inventory_world["wh_a1"]), _u(inventory_world["tenant_b"])
            )
            assert product_b_view is None
            assert warehouse_b_view is None

    async def test_create_product_and_get(self, inventory_world: dict[str, str]) -> None:
        tenant = _u(inventory_world["tenant_a"])
        async with async_session_factory() as session:
            repo = InventoryRepository(session)
            created = await repo.create_product(
                Product(tenant_id=tenant, sku="SKU-NEW", name="New Widget")
            )
            await session.commit()
            assert created.id is not None
            assert created.cost_price.is_zero()
            assert created.sell_price.currency == "USD"

    async def test_soft_delete_product(self, inventory_world: dict[str, str]) -> None:
        tenant = _u(inventory_world["tenant_a"])
        async with async_session_factory() as session:
            repo = InventoryRepository(session)
            created = await repo.create_product(
                Product(tenant_id=tenant, sku="SKU-SOFT", name="Soft Widget")
            )
            await repo.deactivate_product(created.id, tenant)
            await session.commit()

            assert await repo.get_product(created.id, tenant) is not None
            active = await repo.list_products(tenant)
            assert all(p.sku != "SKU-SOFT" for p in active)
            all_products = await repo.list_products(tenant, include_inactive=True)
            assert any(p.sku == "SKU-SOFT" for p in all_products)
