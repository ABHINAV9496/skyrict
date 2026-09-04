"""Inventory service unit tests - §4 business rules + §5.4 reservation port.

Fake repository (in-memory ledger) + fake audit service + patched event
producer: no DB, no IO. Covers:
  Rule 1 - every change is a ledger movement; levels recomputed.
  Rule 2 - no negative stock (service pre-check -> InsufficientStockError).
  Rule 3 - transfers atomic (two movements sharing one ref, or none).
  Rule 4 - reorder alert fires once per breach crossing, never repeatedly.
  §5.4  - qty_reserved never exceeds qty_on_hand; release never below zero;
          fulfil consumes the reservation and writes the sale outflow.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

import core.features.inventory.service as service_module
from core.audit_events import (
    PRODUCT_CREATED,
    PRODUCT_DEACTIVATED,
    PRODUCT_REACTIVATED,
    PRODUCT_UPDATED,
    STOCK_ADJUSTED,
    STOCK_REORDER_ALERTED,
    STOCK_TRANSFERRED,
    WAREHOUSE_CREATED,
    WAREHOUSE_DEACTIVATED,
    WAREHOUSE_REACTIVATED,
    WAREHOUSE_UPDATED,
)
from core.core.exceptions import (
    DuplicateSkuError,
    InactiveItemError,
    InsufficientStockError,
    MovementImmutableError,
    StockReservedError,
    TransferRequiresDistinctWarehousesError,
)
from core.domain.entities import Product, StockLevel, StockMovement, Warehouse
from core.domain.value_objects import Money, StockMovementType
from core.features.inventory.repository import _UNSET
from core.features.inventory.service import InventoryService
from skyrict_common.exceptions import NotFoundError, PermissionDeniedError, ValidationError

TENANT = uuid.uuid4()


class FakeAuditService:
    """Records audit.log() calls for assertions."""

    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    async def log(
        self,
        *,
        action: str,
        target: str,
        user_id: str | None = None,
        details: dict[str, object] | None = None,
        tenant_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.entries.append(
            {
                "action": action,
                "target": target,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "details": details,
                "ip_address": ip_address,
                "user_agent": user_agent,
            }
        )

    def actions(self) -> list[str]:
        return [entry["action"] for entry in self.entries]  # type: ignore[return-value]


class FakeRepo:
    """In-memory ledger emulating the repository's recompute semantics.

    ``add_movement`` recomputes the level exactly like the real repository:
    ``qty_on_hand`` = sum of non-reservation movements, ``qty_reserved`` = net
    of reservation/release. The ``apply_*`` guards mirror the atomic conditional
    UPDATEs (return False instead of raising).
    """

    def __init__(self) -> None:
        self.products: dict[uuid.UUID, Product] = {}
        self.warehouses: dict[uuid.UUID, Warehouse] = {}
        self.movements: list[StockMovement] = []
        self.levels: dict[tuple[uuid.UUID, uuid.UUID], StockLevel] = {}
        self.committed = 0

    # --- transactions ---

    async def commit(self) -> None:
        self.committed += 1

    # --- products ---

    async def create_product(self, product: Product) -> Product:
        product = Product(
            id=uuid.uuid4(),
            tenant_id=product.tenant_id,
            sku=product.sku,
            name=product.name,
            category=product.category,
            unit=product.unit,
            cost_price=product.cost_price,
            sell_price=product.sell_price,
            reorder_point=product.reorder_point,
            is_active=product.is_active,
        )
        self.products[product.id] = product
        return product

    async def get_product(self, product_id: uuid.UUID, tenant_id: uuid.UUID) -> Product | None:
        product = self.products.get(product_id)
        return product if product is not None and product.tenant_id == tenant_id else None

    async def get_product_by_sku(self, sku: str, tenant_id: uuid.UUID) -> Product | None:
        for product in self.products.values():
            if product.tenant_id == tenant_id and product.sku == sku:
                return product
        return None

    async def update_product(
        self,
        product_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        sku: str | object = _UNSET,
        name: str | object = _UNSET,
        category: str | object | None = _UNSET,
        unit: str | object | None = _UNSET,
        cost_price: object = _UNSET,
        sell_price: object = _UNSET,
        reorder_point: object = _UNSET,
    ) -> Product | None:
        product = self.products.get(product_id)
        if product is None or product.tenant_id != tenant_id:
            return None
        updated = Product(
            id=product.id,
            tenant_id=product.tenant_id,
            sku=product.sku if sku is _UNSET else str(sku),
            name=product.name if name is _UNSET else str(name),
            category=product.category if category is _UNSET else (category or None),
            unit=product.unit if unit is _UNSET else (unit or None),
            cost_price=product.cost_price if cost_price is _UNSET else cost_price,
            sell_price=product.sell_price if sell_price is _UNSET else sell_price,
            reorder_point=(product.reorder_point if reorder_point is _UNSET else reorder_point),
            is_active=product.is_active,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )
        self.products[product_id] = updated
        return updated

    async def deactivate_product(
        self, product_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Product | None:
        product = self.products.get(product_id)
        if product is None or product.tenant_id != tenant_id:
            return None
        deactivated = Product(
            id=product.id,
            tenant_id=product.tenant_id,
            sku=product.sku,
            name=product.name,
            category=product.category,
            unit=product.unit,
            cost_price=product.cost_price,
            sell_price=product.sell_price,
            reorder_point=product.reorder_point,
            is_active=False,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )
        self.products[product_id] = deactivated
        return deactivated

    async def reactivate_product(
        self, product_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Product | None:
        product = self.products.get(product_id)
        if product is None or product.tenant_id != tenant_id:
            return None
        reactivated = Product(
            id=product.id,
            tenant_id=product.tenant_id,
            sku=product.sku,
            name=product.name,
            category=product.category,
            unit=product.unit,
            cost_price=product.cost_price,
            sell_price=product.sell_price,
            reorder_point=product.reorder_point,
            is_active=True,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )
        self.products[product_id] = reactivated
        return reactivated

    async def list_products(self, tenant_id: uuid.UUID, **kwargs):
        return [p for p in self.products.values() if p.tenant_id == tenant_id]

    async def count_products(self, tenant_id: uuid.UUID, **kwargs) -> int:
        return len([p for p in self.products.values() if p.tenant_id == tenant_id])

    # --- warehouses ---

    async def create_warehouse(self, warehouse: Warehouse) -> Warehouse:
        warehouse = Warehouse(
            id=uuid.uuid4(),
            tenant_id=warehouse.tenant_id,
            name=warehouse.name,
            location=warehouse.location,
            is_active=warehouse.is_active,
        )
        self.warehouses[warehouse.id] = warehouse
        return warehouse

    async def get_warehouse(
        self, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Warehouse | None:
        warehouse = self.warehouses.get(warehouse_id)
        return warehouse if warehouse is not None and warehouse.tenant_id == tenant_id else None

    async def update_warehouse(
        self,
        warehouse_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        name: str | object = _UNSET,
        location: str | object | None = _UNSET,
    ) -> Warehouse | None:
        warehouse = self.warehouses.get(warehouse_id)
        if warehouse is None or warehouse.tenant_id != tenant_id:
            return None
        updated = Warehouse(
            id=warehouse.id,
            tenant_id=warehouse.tenant_id,
            name=warehouse.name if name is _UNSET else str(name),
            location=warehouse.location if location is _UNSET else (location or None),
            is_active=warehouse.is_active,
            created_at=warehouse.created_at,
            updated_at=warehouse.updated_at,
        )
        self.warehouses[warehouse_id] = updated
        return updated

    async def deactivate_warehouse(
        self, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Warehouse | None:
        warehouse = self.warehouses.get(warehouse_id)
        if warehouse is None or warehouse.tenant_id != tenant_id:
            return None
        deactivated = Warehouse(
            id=warehouse.id,
            tenant_id=warehouse.tenant_id,
            name=warehouse.name,
            location=warehouse.location,
            is_active=False,
            created_at=warehouse.created_at,
            updated_at=warehouse.updated_at,
        )
        self.warehouses[warehouse_id] = deactivated
        return deactivated

    async def reactivate_warehouse(
        self, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Warehouse | None:
        warehouse = self.warehouses.get(warehouse_id)
        if warehouse is None or warehouse.tenant_id != tenant_id:
            return None
        reactivated = Warehouse(
            id=warehouse.id,
            tenant_id=warehouse.tenant_id,
            name=warehouse.name,
            location=warehouse.location,
            is_active=True,
            created_at=warehouse.created_at,
            updated_at=warehouse.updated_at,
        )
        self.warehouses[warehouse_id] = reactivated
        return reactivated

    async def list_warehouses(self, tenant_id: uuid.UUID, **kwargs):
        return [w for w in self.warehouses.values() if w.tenant_id == tenant_id]

    async def count_warehouses(self, tenant_id: uuid.UUID, **kwargs) -> int:
        return len([w for w in self.warehouses.values() if w.tenant_id == tenant_id])

    # --- stock levels ---

    async def get_stock_level(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> StockLevel | None:
        return self.levels.get((product_id, warehouse_id))

    async def recompute_stock_level(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> StockLevel:
        on_hand = Decimal("0")
        reserved = Decimal("0")
        for movement in self.movements:
            if (
                movement.tenant_id == tenant_id
                and movement.product_id == product_id
                and movement.warehouse_id == warehouse_id
            ):
                if movement.movement_type in (
                    StockMovementType.RESERVATION,
                    StockMovementType.RELEASE,
                ):
                    reserved += movement.qty
                else:
                    on_hand += movement.qty
        level = StockLevel(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            qty_on_hand=on_hand,
            qty_reserved=reserved,
        )
        self.levels[(product_id, warehouse_id)] = level
        return level

    async def list_stock_levels(self, tenant_id: uuid.UUID, **kwargs):
        return list(self.levels.values())

    async def count_stock_levels(self, tenant_id: uuid.UUID, **kwargs) -> int:
        return len(self.levels)

    async def sum_stock_by_product(
        self, product_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> tuple[Decimal, Decimal]:
        on_hand = Decimal("0")
        reserved = Decimal("0")
        for (pid, _wid), level in self.levels.items():
            if level.tenant_id == tenant_id and pid == product_id:
                on_hand += level.qty_on_hand
                reserved += level.qty_reserved
        return on_hand, reserved

    async def sum_stock_by_warehouse(
        self, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> tuple[Decimal, Decimal]:
        on_hand = Decimal("0")
        reserved = Decimal("0")
        for (_pid, wid), level in self.levels.items():
            if level.tenant_id == tenant_id and wid == warehouse_id:
                on_hand += level.qty_on_hand
                reserved += level.qty_reserved
        return on_hand, reserved

    # --- guarded reservation updates ---

    async def apply_reservation_qty(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, qty: Decimal, tenant_id: uuid.UUID
    ) -> bool:
        level = self.levels.get((product_id, warehouse_id))
        if level is None:
            return False
        return level.qty_reserved + qty <= level.qty_on_hand

    async def apply_release_qty(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, qty: Decimal, tenant_id: uuid.UUID
    ) -> bool:
        level = self.levels.get((product_id, warehouse_id))
        if level is None:
            return False
        return level.qty_reserved - qty >= 0

    async def apply_consume_qty(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, qty: Decimal, tenant_id: uuid.UUID
    ) -> bool:
        return await self.apply_release_qty(product_id, warehouse_id, qty, tenant_id)

    # --- movements ---

    async def get_movement_by_ref(
        self,
        ref_type: str,
        ref_id: str,
        warehouse_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> StockMovement | None:
        for movement in self.movements:
            if (
                movement.tenant_id == tenant_id
                and movement.ref_type == ref_type
                and movement.ref_id == ref_id
                and movement.warehouse_id == warehouse_id
            ):
                return movement
        return None

    async def add_movement(self, movement: StockMovement) -> StockMovement:
        existing = await self.get_movement_by_ref(
            movement.ref_type, movement.ref_id, movement.warehouse_id, movement.tenant_id
        )
        if existing is not None:
            return existing
        created = StockMovement(
            id=uuid.uuid4(),
            tenant_id=movement.tenant_id,
            product_id=movement.product_id,
            warehouse_id=movement.warehouse_id,
            movement_type=movement.movement_type,
            qty=movement.qty,
            ref_type=movement.ref_type,
            ref_id=movement.ref_id,
        )
        self.movements.append(created)
        await self.recompute_stock_level(
            movement.product_id, movement.warehouse_id, movement.tenant_id
        )
        return created

    async def list_movements(self, tenant_id: uuid.UUID, **kwargs):
        return list(self.movements)

    async def count_movements(self, tenant_id: uuid.UUID, **kwargs) -> int:
        return len(self.movements)

    async def list_low_stock(self, tenant_id: uuid.UUID, **kwargs):
        result = []
        for (product_id, _warehouse_id), level in self.levels.items():
            product = self.products.get(product_id)
            if (
                product is not None
                and product.is_active
                and level.qty_on_hand <= product.reorder_point
            ):
                result.append((level, product))
        return result

    async def count_low_stock(self, tenant_id: uuid.UUID) -> int:
        return len(await self.list_low_stock(tenant_id))


class FakeEvents:
    """Captures emit_stock_level_changed calls (patched onto the service module)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def emit(
        self,
        *,
        tenant_id: str | uuid.UUID,
        product_id: str | uuid.UUID,
        warehouse_id: str | uuid.UUID,
        qty_on_hand: Decimal,
        reorder_point: Decimal,
        breach_crossed: bool,
    ) -> None:
        self.calls.append(
            {
                "tenant_id": str(tenant_id),
                "product_id": str(product_id),
                "warehouse_id": str(warehouse_id),
                "qty_on_hand": qty_on_hand,
                "reorder_point": reorder_point,
                "breach_crossed": breach_crossed,
            }
        )


class FakeProductEvents:
    """Captures product snapshot emit calls (patched onto the service module)."""

    def __init__(self) -> None:
        self.upserted: list[dict[str, object]] = []
        self.removed: list[dict[str, object]] = []

    async def upsert(
        self,
        *,
        tenant_id: str | uuid.UUID,
        product_id: str | uuid.UUID,
        sku: str,
        name: str,
        category: str | None,
        unit: str | None,
    ) -> None:
        self.upserted.append(
            {
                "tenant_id": str(tenant_id),
                "product_id": str(product_id),
                "sku": sku,
                "name": name,
                "category": category,
                "unit": unit,
            }
        )

    async def remove(
        self,
        *,
        tenant_id: str | uuid.UUID,
        product_id: str | uuid.UUID,
    ) -> None:
        self.removed.append({"tenant_id": str(tenant_id), "product_id": str(product_id)})


@pytest.fixture()
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture()
def audit() -> FakeAuditService:
    return FakeAuditService()


@pytest.fixture()
def events() -> FakeEvents:
    return FakeEvents()


@pytest.fixture()
def product_events() -> FakeProductEvents:
    return FakeProductEvents()


@pytest.fixture()
def service(
    repo: FakeRepo, audit: FakeAuditService, monkeypatch: pytest.MonkeyPatch
) -> InventoryService:
    return InventoryService(repo, audit, approve_threshold=Decimal("100.00"))


@pytest.fixture()
def patched_events(
    service: InventoryService, events: FakeEvents, monkeypatch: pytest.MonkeyPatch
) -> FakeEvents:
    monkeypatch.setattr(service_module, "emit_stock_level_changed", events.emit)
    return events


@pytest.fixture()
def patched_product_events(
    repo: FakeRepo,
    product_events: FakeProductEvents,
    monkeypatch: pytest.MonkeyPatch,
) -> FakeProductEvents:
    monkeypatch.setattr(service_module, "emit_inventory_product_upserted", product_events.upsert)
    monkeypatch.setattr(service_module, "emit_inventory_product_removed", product_events.remove)
    return product_events


async def _seed_product(
    repo: FakeRepo, *, sku: str = "SKU-1", reorder: Decimal = Decimal("0")
) -> Product:
    return await repo.create_product(
        Product(tenant_id=TENANT, sku=sku, name="Widget", reorder_point=reorder)
    )


async def _seed_warehouse(repo: FakeRepo, *, name: str = "Main") -> Warehouse:
    return await repo.create_warehouse(Warehouse(tenant_id=TENANT, name=name))


async def _seed_receipt(
    repo: FakeRepo, product_id: uuid.UUID, warehouse_id: uuid.UUID, qty: Decimal
) -> None:
    await repo.add_movement(
        StockMovement(
            tenant_id=TENANT,
            product_id=product_id,
            warehouse_id=warehouse_id,
            movement_type=StockMovementType.RECEIPT,
            qty=qty,
            ref_type="po",
            ref_id=str(uuid.uuid4()),
        )
    )


class TestCreateProduct:
    async def test_creates_audits_and_commits(
        self, service: InventoryService, repo: FakeRepo, audit: FakeAuditService
    ) -> None:
        product = await service.create_product(TENANT, sku="SKU-1", name="Widget")
        assert product.id is not None
        assert repo.committed == 1
        assert audit.actions() == [PRODUCT_CREATED]

    async def test_emits_upserted_event_with_catalog_fields(
        self,
        service: InventoryService,
        repo: FakeRepo,
        patched_product_events: FakeProductEvents,
    ) -> None:
        product = await service.create_product(
            TENANT,
            sku="CBL-CABLE",
            name="Cat6 Patch Cable",
            category="Networking",
            unit="m",
        )
        assert product.id is not None
        assert patched_product_events.removed == []
        assert patched_product_events.upserted == [
            {
                "tenant_id": str(TENANT),
                "product_id": str(product.id),
                "sku": "CBL-CABLE",
                "name": "Cat6 Patch Cable",
                "category": "Networking",
                "unit": "m",
            }
        ]

    async def test_duplicate_sku_raises_409(
        self, service: InventoryService, repo: FakeRepo, audit: FakeAuditService
    ) -> None:
        await service.create_product(TENANT, sku="SKU-1", name="Widget")
        with pytest.raises(DuplicateSkuError):
            await service.create_product(TENANT, sku="SKU-1", name="Other")
        assert repo.committed == 1  # nothing committed for the failed replay

    async def test_empty_sku_rejected(self, service: InventoryService) -> None:
        with pytest.raises(ValidationError):
            await service.create_product(TENANT, sku="  ", name="Widget")


class TestCreateWarehouse:
    async def test_creates_audits_and_commits(
        self, service: InventoryService, repo: FakeRepo, audit: FakeAuditService
    ) -> None:
        warehouse = await service.create_warehouse(TENANT, name="Main", location="A1")
        assert warehouse.id is not None
        assert repo.committed == 1
        assert audit.actions() == [WAREHOUSE_CREATED]


class TestUpdateProduct:
    async def test_partial_update_audits_and_commits(
        self, service: InventoryService, repo: FakeRepo, audit: FakeAuditService
    ) -> None:
        product = await _seed_product(repo, sku="SKU-1")
        updated = await service.update_product(
            TENANT, product.id, name="Renamed", sell_price=Money(Decimal("9.99"), "USD")
        )
        assert updated.name == "Renamed"
        assert updated.sku == "SKU-1"  # untouched field stays
        assert updated.sell_price == Money(Decimal("9.99"), "USD")
        assert repo.committed == 1
        assert audit.actions() == [PRODUCT_UPDATED]

    async def test_same_sku_does_not_clash(
        self, service: InventoryService, repo: FakeRepo, audit: FakeAuditService
    ) -> None:
        product = await _seed_product(repo, sku="SKU-1")
        updated = await service.update_product(TENANT, product.id, sku="SKU-1", name="Keep")
        assert updated.sku == "SKU-1"
        assert audit.actions() == [PRODUCT_UPDATED]

    async def test_emits_upserted_event_after_update(
        self,
        service: InventoryService,
        repo: FakeRepo,
        patched_product_events: FakeProductEvents,
    ) -> None:
        product = await _seed_product(repo, sku="SKU-1")
        updated = await service.update_product(TENANT, product.id, name="Renamed")
        assert updated.id is not None
        assert patched_product_events.upserted == [
            {
                "tenant_id": str(TENANT),
                "product_id": str(product.id),
                "sku": "SKU-1",
                "name": "Renamed",
                "category": None,
                "unit": None,
            }
        ]
        assert patched_product_events.removed == []

    async def test_duplicate_sku_of_other_product_raises_409(
        self, service: InventoryService, repo: FakeRepo, audit: FakeAuditService
    ) -> None:
        await _seed_product(repo, sku="SKU-1")
        other = await _seed_product(repo, sku="SKU-2")
        with pytest.raises(DuplicateSkuError):
            await service.update_product(TENANT, other.id, sku="SKU-1")
        assert repo.committed == 0  # nothing committed for the failed edit

    async def test_unknown_product_raises_404(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        with pytest.raises(NotFoundError):
            await service.update_product(TENANT, uuid.uuid4(), name="Ghost")

    async def test_empty_sku_rejected(self, service: InventoryService, repo: FakeRepo) -> None:
        product = await _seed_product(repo, sku="SKU-1")
        with pytest.raises(ValidationError):
            await service.update_product(TENANT, product.id, sku="  ")


class TestUpdateWarehouse:
    async def test_partial_update_audits_and_commits(
        self, service: InventoryService, repo: FakeRepo, audit: FakeAuditService
    ) -> None:
        warehouse = await _seed_warehouse(repo, name="Main")
        updated = await service.update_warehouse(TENANT, warehouse.id, location="B2")
        assert updated.name == "Main"
        assert updated.location == "B2"
        assert repo.committed == 1
        assert audit.actions() == [WAREHOUSE_UPDATED]

    async def test_unknown_warehouse_raises_404(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        with pytest.raises(NotFoundError):
            await service.update_warehouse(TENANT, uuid.uuid4(), name="Ghost")


class TestDeactivateProduct:
    async def test_soft_deletes_audits_and_commits(
        self, service: InventoryService, repo: FakeRepo, audit: FakeAuditService
    ) -> None:
        product = await _seed_product(repo, sku="SKU-1")
        deactivated = await service.deactivate_product(TENANT, product.id)
        assert deactivated.is_active is False
        assert repo.committed == 1
        assert audit.actions() == [PRODUCT_DEACTIVATED]

    async def test_allows_when_on_hand_remains(
        self, service: InventoryService, repo: FakeRepo, audit: FakeAuditService
    ) -> None:
        product = await _seed_product(repo, sku="SKU-1")
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("10"))

        deactivated = await service.deactivate_product(TENANT, product.id)
        assert deactivated.is_active is False
        assert repo.committed == 1
        assert audit.actions() == [PRODUCT_DEACTIVATED]
        assert audit.entries[0]["details"] == {
            "sku": "SKU-1",
            "name": "Widget",
            "on_hand_qty": "10",
            "reserved_qty": "0",
        }

    async def test_blocks_when_reserved_remains(
        self, service: InventoryService, repo: FakeRepo, audit: FakeAuditService
    ) -> None:
        product = await _seed_product(repo, sku="SKU-1")
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("10"))
        await service.reserve_stock(product.id, warehouse.id, Decimal("4"), TENANT, ref_id="SO-DEL")

        with pytest.raises(StockReservedError):
            await service.deactivate_product(TENANT, product.id)
        assert audit.actions() == []
        assert repo.committed == 1  # only the reserve's commit - deactivate never commits
        remaining = await repo.get_product(product.id, TENANT)
        assert remaining is not None and remaining.is_active is True

    async def test_emits_removed_event_after_deactivate(
        self,
        service: InventoryService,
        repo: FakeRepo,
        patched_product_events: FakeProductEvents,
    ) -> None:
        product = await _seed_product(repo, sku="SKU-1")
        deactivated = await service.deactivate_product(TENANT, product.id)
        assert deactivated.is_active is False
        assert patched_product_events.upserted == []
        assert patched_product_events.removed == [
            {"tenant_id": str(TENANT), "product_id": str(product.id)}
        ]

    async def test_unknown_product_raises_404(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        with pytest.raises(NotFoundError):
            await service.deactivate_product(TENANT, uuid.uuid4())


class TestDeactivateWarehouse:
    async def test_soft_deletes_audits_and_commits(
        self, service: InventoryService, repo: FakeRepo, audit: FakeAuditService
    ) -> None:
        warehouse = await _seed_warehouse(repo, name="Main")
        deactivated = await service.deactivate_warehouse(TENANT, warehouse.id)
        assert deactivated.is_active is False
        assert repo.committed == 1
        assert audit.actions() == [WAREHOUSE_DEACTIVATED]

    async def test_allows_when_on_hand_remains(
        self, service: InventoryService, repo: FakeRepo, audit: FakeAuditService
    ) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("5"))

        deactivated = await service.deactivate_warehouse(TENANT, warehouse.id)
        assert deactivated.is_active is False
        assert repo.committed == 1
        assert audit.actions() == [WAREHOUSE_DEACTIVATED]
        assert audit.entries[0]["details"]["on_hand_qty"] == "5"

    async def test_blocks_when_reserved_remains(
        self, service: InventoryService, repo: FakeRepo, audit: FakeAuditService
    ) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("10"))
        await service.reserve_stock(
            product.id, warehouse.id, Decimal("4"), TENANT, ref_id="SO-WHDEL"
        )

        with pytest.raises(StockReservedError):
            await service.deactivate_warehouse(TENANT, warehouse.id)
        assert audit.actions() == []
        remaining = await repo.get_warehouse(warehouse.id, TENANT)
        assert remaining is not None and remaining.is_active is True

    async def test_unknown_warehouse_raises_404(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        with pytest.raises(NotFoundError):
            await service.deactivate_warehouse(TENANT, uuid.uuid4())


class TestReactivateProduct:
    async def test_reactivates_audits_and_commits(
        self, service: InventoryService, repo: FakeRepo, audit: FakeAuditService
    ) -> None:
        product = await _seed_product(repo, sku="SKU-1")
        await repo.deactivate_product(product.id, TENANT)

        reactivated = await service.reactivate_product(TENANT, product.id)
        assert reactivated.is_active is True
        assert repo.committed == 1
        assert audit.actions() == [PRODUCT_REACTIVATED]

    async def test_emits_upserted_event_after_reactivate(
        self,
        service: InventoryService,
        repo: FakeRepo,
        patched_product_events: FakeProductEvents,
    ) -> None:
        product = await _seed_product(repo, sku="SKU-1")
        await repo.deactivate_product(product.id, TENANT)

        reactivated = await service.reactivate_product(TENANT, product.id)
        assert reactivated.is_active is True
        assert patched_product_events.removed == []
        assert patched_product_events.upserted == [
            {
                "tenant_id": str(TENANT),
                "product_id": str(product.id),
                "sku": "SKU-1",
                "name": "Widget",
                "category": None,
                "unit": None,
            }
        ]

    async def test_unknown_product_raises_404(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        with pytest.raises(NotFoundError):
            await service.reactivate_product(TENANT, uuid.uuid4())


class TestReactivateWarehouse:
    async def test_reactivates_audits_and_commits(
        self, service: InventoryService, repo: FakeRepo, audit: FakeAuditService
    ) -> None:
        warehouse = await _seed_warehouse(repo, name="Main")
        await repo.deactivate_warehouse(warehouse.id, TENANT)

        reactivated = await service.reactivate_warehouse(TENANT, warehouse.id)
        assert reactivated.is_active is True
        assert repo.committed == 1
        assert audit.actions() == [WAREHOUSE_REACTIVATED]

    async def test_unknown_warehouse_raises_404(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        with pytest.raises(NotFoundError):
            await service.reactivate_warehouse(TENANT, uuid.uuid4())


class TestPostingBlock:
    async def test_transfer_on_inactive_product_rejected(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        product = await _seed_product(repo)
        await repo.deactivate_product(product.id, TENANT)
        src = await _seed_warehouse(repo)
        dst = await _seed_warehouse(repo, name="Other")

        with pytest.raises(InactiveItemError):
            await service.transfer_stock(
                TENANT,
                product_id=product.id,
                from_warehouse_id=src.id,
                to_warehouse_id=dst.id,
                qty=Decimal("1"),
                ref_id="TR-BLOCK",
            )
        assert repo.committed == 0

    async def test_transfer_from_inactive_warehouse_rejected(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        product = await _seed_product(repo)
        src = await _seed_warehouse(repo)
        await repo.deactivate_warehouse(src.id, TENANT)
        dst = await _seed_warehouse(repo, name="Other")

        with pytest.raises(InactiveItemError):
            await service.transfer_stock(
                TENANT,
                product_id=product.id,
                from_warehouse_id=src.id,
                to_warehouse_id=dst.id,
                qty=Decimal("1"),
                ref_id="TR-BLOCK-WH",
            )
        assert repo.committed == 0

    async def test_reserve_on_inactive_product_rejected(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        product = await _seed_product(repo)
        await repo.deactivate_product(product.id, TENANT)
        warehouse = await _seed_warehouse(repo)

        with pytest.raises(InactiveItemError):
            await service.reserve_stock(
                product.id, warehouse.id, Decimal("1"), TENANT, ref_id="SO-BLOCK"
            )

    async def test_fulfil_on_inactive_warehouse_rejected(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("10"))
        await service.reserve_stock(
            product.id, warehouse.id, Decimal("4"), TENANT, ref_id="SO-FULFIL"
        )
        await repo.deactivate_warehouse(warehouse.id, TENANT)

        with pytest.raises(InactiveItemError):
            await service.fulfil_order(
                product.id, warehouse.id, Decimal("4"), TENANT, ref_id="SO-FULFIL"
            )

    async def test_adjust_on_inactive_product_allowed_write_off(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("5"))
        await repo.deactivate_product(product.id, TENANT)

        movement = await service.adjust_stock(
            TENANT,
            product_id=product.id,
            warehouse_id=warehouse.id,
            qty=Decimal("-5"),
            reason="write-off",
            ref_id="ADJ-WRITEOFF",
        )
        assert movement.qty == Decimal("-5")
        level = await repo.get_stock_level(product.id, warehouse.id, TENANT)
        assert level is not None and level.qty_on_hand == Decimal("0")


class TestAlertFiltering:
    async def test_alerts_exclude_inactive_products(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        product = await _seed_product(repo, reorder=Decimal("5"))
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("4"))
        await repo.deactivate_product(product.id, TENANT)

        alerts = await service.list_alerts(TENANT)
        assert alerts == []
        assert await service.count_alerts(TENANT) == 0


class TestAdjustStock:
    async def test_receipt_and_positive_adjustment_update_level(
        self,
        service: InventoryService,
        repo: FakeRepo,
        audit: FakeAuditService,
        patched_events: FakeEvents,
    ) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("10"))

        movement = await service.adjust_stock(
            TENANT,
            product_id=product.id,
            warehouse_id=warehouse.id,
            qty=Decimal("5"),
            reason="restock",
            ref_id="ADJ-1",
        )
        level = await repo.get_stock_level(product.id, warehouse.id, TENANT)
        assert movement.movement_type is StockMovementType.ADJUSTMENT
        assert movement.qty == Decimal("5")
        assert level is not None and level.qty_on_hand == Decimal("15")
        assert audit.actions() == [STOCK_ADJUSTED]
        assert patched_events.calls[-1]["breach_crossed"] is False

    async def test_negative_adjustment_within_stock(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("10"))

        movement = await service.adjust_stock(
            TENANT,
            product_id=product.id,
            warehouse_id=warehouse.id,
            qty=Decimal("-4"),
            reason="damage",
            ref_id="ADJ-2",
        )
        level = await repo.get_stock_level(product.id, warehouse.id, TENANT)
        assert movement.qty == Decimal("-4")
        assert level is not None and level.qty_on_hand == Decimal("6")

    async def test_negative_adjustment_below_zero_rejected(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("3"))

        with pytest.raises(InsufficientStockError):
            await service.adjust_stock(
                TENANT,
                product_id=product.id,
                warehouse_id=warehouse.id,
                qty=Decimal("-5"),
                reason="oops",
                ref_id="ADJ-3",
            )
        assert repo.committed == 0
        assert await repo.get_movement_by_ref("adjustment", "ADJ-3", warehouse.id, TENANT) is None

    async def test_replay_rejected(self, service: InventoryService, repo: FakeRepo) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("10"))

        await service.adjust_stock(
            TENANT,
            product_id=product.id,
            warehouse_id=warehouse.id,
            qty=Decimal("2"),
            reason="restock",
            ref_id="ADJ-REPLAY",
        )
        with pytest.raises(MovementImmutableError):
            await service.adjust_stock(
                TENANT,
                product_id=product.id,
                warehouse_id=warehouse.id,
                qty=Decimal("2"),
                reason="restock",
                ref_id="ADJ-REPLAY",
            )

    async def test_reason_required(self, service: InventoryService, repo: FakeRepo) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        with pytest.raises(ValidationError):
            await service.adjust_stock(
                TENANT,
                product_id=product.id,
                warehouse_id=warehouse.id,
                qty=Decimal("1"),
                reason="  ",
                ref_id="ADJ-4",
            )

    async def test_zero_qty_rejected(self, service: InventoryService, repo: FakeRepo) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        with pytest.raises(ValidationError):
            await service.adjust_stock(
                TENANT,
                product_id=product.id,
                warehouse_id=warehouse.id,
                qty=Decimal("0"),
                reason="nope",
                ref_id="ADJ-5",
            )

    async def test_above_threshold_requires_approval(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("1000"))

        with pytest.raises(PermissionDeniedError):
            await service.adjust_stock(
                TENANT,
                product_id=product.id,
                warehouse_id=warehouse.id,
                qty=Decimal("150"),
                reason="big",
                ref_id="ADJ-APPROVE",
            )
        assert repo.committed == 0

        movement = await service.adjust_stock(
            TENANT,
            product_id=product.id,
            warehouse_id=warehouse.id,
            qty=Decimal("150"),
            reason="big",
            ref_id="ADJ-APPROVE",
            approved=True,
        )
        assert movement.qty == Decimal("150")

    async def test_at_threshold_does_not_need_approval(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("1000"))

        movement = await service.adjust_stock(
            TENANT,
            product_id=product.id,
            warehouse_id=warehouse.id,
            qty=Decimal("100"),
            reason="at limit",
            ref_id="ADJ-LIMIT",
        )
        assert movement.qty == Decimal("100")


class TestReorderAlert:
    async def test_fires_once_per_breach_crossing(
        self,
        service: InventoryService,
        repo: FakeRepo,
        audit: FakeAuditService,
        patched_events: FakeEvents,
    ) -> None:
        product = await _seed_product(repo, sku="SKU-ROP", reorder=Decimal("5"))
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("10"))

        # First movement crosses the point (10 -> 4): must fire.
        await service.adjust_stock(
            TENANT,
            product_id=product.id,
            warehouse_id=warehouse.id,
            qty=Decimal("-6"),
            reason="sale",
            ref_id="ROP-1",
        )
        assert patched_events.calls[-1]["breach_crossed"] is True
        assert patched_events.calls[-1]["qty_on_hand"] == Decimal("4")
        assert audit.actions() == [STOCK_ADJUSTED, STOCK_REORDER_ALERTED]

        # Second movement while already below (4 -> 2): must NOT re-fire.
        await service.adjust_stock(
            TENANT,
            product_id=product.id,
            warehouse_id=warehouse.id,
            qty=Decimal("-2"),
            reason="sale",
            ref_id="ROP-2",
        )
        assert patched_events.calls[-1]["breach_crossed"] is False
        assert patched_events.calls[-1]["qty_on_hand"] == Decimal("2")
        assert audit.actions().count(STOCK_REORDER_ALERTED) == 1

        # Recovery then a second crossing (0 -> 10 -> 3): fires again.
        await service.adjust_stock(
            TENANT,
            product_id=product.id,
            warehouse_id=warehouse.id,
            qty=Decimal("8"),
            reason="restock",
            ref_id="ROP-3",
        )
        await service.adjust_stock(
            TENANT,
            product_id=product.id,
            warehouse_id=warehouse.id,
            qty=Decimal("-7"),
            reason="sale",
            ref_id="ROP-4",
        )
        assert patched_events.calls[-1]["breach_crossed"] is True
        assert audit.actions().count(STOCK_REORDER_ALERTED) == 2


class TestTransferStock:
    async def test_atomic_pair_shares_ref(
        self,
        service: InventoryService,
        repo: FakeRepo,
        audit: FakeAuditService,
        patched_events: FakeEvents,
    ) -> None:
        product = await _seed_product(repo)
        src = await _seed_warehouse(repo, name="Source")
        dst = await _seed_warehouse(repo, name="Destination")
        await _seed_receipt(repo, product.id, src.id, Decimal("10"))

        out_movement, in_movement = await service.transfer_stock(
            TENANT,
            product_id=product.id,
            from_warehouse_id=src.id,
            to_warehouse_id=dst.id,
            qty=Decimal("4"),
            ref_id="TR-1",
        )
        src_level = await repo.get_stock_level(product.id, src.id, TENANT)
        dst_level = await repo.get_stock_level(product.id, dst.id, TENANT)
        assert out_movement.qty == Decimal("-4")
        assert in_movement.qty == Decimal("4")
        assert out_movement.ref_id == in_movement.ref_id == "TR-1"
        assert src_level is not None and src_level.qty_on_hand == Decimal("6")
        assert dst_level is not None and dst_level.qty_on_hand == Decimal("4")
        assert audit.actions() == [STOCK_TRANSFERRED]
        assert len(patched_events.calls) == 2

    async def test_same_warehouse_rejected(self, service: InventoryService, repo: FakeRepo) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        with pytest.raises(TransferRequiresDistinctWarehousesError):
            await service.transfer_stock(
                TENANT,
                product_id=product.id,
                from_warehouse_id=warehouse.id,
                to_warehouse_id=warehouse.id,
                qty=Decimal("1"),
                ref_id="TR-2",
            )

    async def test_insufficient_source_rejected(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        product = await _seed_product(repo)
        src = await _seed_warehouse(repo)
        dst = await _seed_warehouse(repo, name="Other")
        await _seed_receipt(repo, product.id, src.id, Decimal("2"))

        with pytest.raises(InsufficientStockError):
            await service.transfer_stock(
                TENANT,
                product_id=product.id,
                from_warehouse_id=src.id,
                to_warehouse_id=dst.id,
                qty=Decimal("3"),
                ref_id="TR-3",
            )
        assert repo.committed == 0
        assert len(repo.movements) == 1  # only the seed receipt

    async def test_replay_rejected(self, service: InventoryService, repo: FakeRepo) -> None:
        product = await _seed_product(repo)
        src = await _seed_warehouse(repo)
        dst = await _seed_warehouse(repo, name="Other")
        await _seed_receipt(repo, product.id, src.id, Decimal("10"))

        await service.transfer_stock(
            TENANT,
            product_id=product.id,
            from_warehouse_id=src.id,
            to_warehouse_id=dst.id,
            qty=Decimal("2"),
            ref_id="TR-REPLAY",
        )
        with pytest.raises(MovementImmutableError):
            await service.transfer_stock(
                TENANT,
                product_id=product.id,
                from_warehouse_id=src.id,
                to_warehouse_id=dst.id,
                qty=Decimal("2"),
                ref_id="TR-REPLAY",
            )


class TestReservation:
    async def test_reserve_within_capacity(
        self, service: InventoryService, repo: FakeRepo, patched_events: FakeEvents
    ) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("10"))

        level = await service.reserve_stock(
            product.id,
            warehouse.id,
            Decimal("4"),
            TENANT,
            ref_id="SO-1",
        )
        assert level.qty_on_hand == Decimal("10")
        assert level.qty_reserved == Decimal("4")
        assert patched_events.calls == []  # reservations don't change on-hand

    async def test_reserve_over_capacity_rejected(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("10"))
        await service.reserve_stock(product.id, warehouse.id, Decimal("8"), TENANT, ref_id="SO-2")

        with pytest.raises(InsufficientStockError):
            await service.reserve_stock(
                product.id, warehouse.id, Decimal("3"), TENANT, ref_id="SO-3"
            )
        level = await repo.get_stock_level(product.id, warehouse.id, TENANT)
        assert level is not None and level.qty_reserved <= level.qty_on_hand

    async def test_reserve_nothing_to_reserve_rejected(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        with pytest.raises(InsufficientStockError):
            await service.reserve_stock(
                product.id, warehouse.id, Decimal("1"), TENANT, ref_id="SO-4"
            )

    async def test_release_never_below_zero(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("10"))
        await service.reserve_stock(product.id, warehouse.id, Decimal("4"), TENANT, ref_id="SO-5")

        with pytest.raises(ValidationError):
            await service.release_reservation(
                product.id, warehouse.id, Decimal("5"), TENANT, ref_id="SO-5"
            )
        level = await repo.get_stock_level(product.id, warehouse.id, TENANT)
        assert level is not None and level.qty_reserved == Decimal("4")

        released = await service.release_reservation(
            product.id, warehouse.id, Decimal("4"), TENANT, ref_id="SO-6"
        )
        assert released.qty_reserved == Decimal("0")

    async def test_fulfil_consumes_reservation_and_writes_sale(
        self, service: InventoryService, repo: FakeRepo, patched_events: FakeEvents
    ) -> None:
        product = await _seed_product(repo, reorder=Decimal("5"))
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("10"))
        await service.reserve_stock(product.id, warehouse.id, Decimal("4"), TENANT, ref_id="SO-7")

        level = await service.fulfil_order(
            product.id,
            warehouse.id,
            Decimal("4"),
            TENANT,
            ref_id="SO-7",
        )
        assert level.qty_on_hand == Decimal("6")
        assert level.qty_reserved == Decimal("0")
        issue_refs = [
            m.ref_id for m in repo.movements if m.movement_type is StockMovementType.ISSUE
        ]
        assert issue_refs == ["SO-7:issue"]
        assert len(patched_events.calls) == 1
        assert patched_events.calls[-1]["qty_on_hand"] == Decimal("6")

    async def test_fulfil_without_reservation_rejected(
        self, service: InventoryService, repo: FakeRepo
    ) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("10"))

        with pytest.raises(InsufficientStockError):
            await service.fulfil_order(
                product.id,
                warehouse.id,
                Decimal("4"),
                TENANT,
                ref_id="SO-8",
            )

    async def test_reserve_replay_rejected(self, service: InventoryService, repo: FakeRepo) -> None:
        product = await _seed_product(repo)
        warehouse = await _seed_warehouse(repo)
        await _seed_receipt(repo, product.id, warehouse.id, Decimal("10"))

        await service.reserve_stock(product.id, warehouse.id, Decimal("4"), TENANT, ref_id="SO-9")
        with pytest.raises(MovementImmutableError):
            await service.reserve_stock(
                product.id, warehouse.id, Decimal("4"), TENANT, ref_id="SO-9"
            )
