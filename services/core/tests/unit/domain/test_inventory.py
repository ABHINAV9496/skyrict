"""Inventory domain tests — movement type enum + entity construction (no DB)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from core.domain.entities import Product, StockLevel, StockMovement, Warehouse
from core.domain.value_objects import Money, StockMovementType
from skyrict_common.exceptions import ValidationError


class TestStockMovementType:
    def test_values_match_ledger_buckets(self) -> None:
        assert {t.value for t in StockMovementType} == {
            "receipt",
            "issue",
            "transfer",
            "adjustment",
            "reservation",
            "release",
        }

    def test_str_enum_semantics(self) -> None:
        assert StockMovementType.RECEIPT == "receipt"
        assert str(StockMovementType.RELEASE) == "release"
        assert StockMovementType("reservation") is StockMovementType.RESERVATION


class TestProduct:
    def test_defaults(self) -> None:
        product = Product(tenant_id=uuid.uuid4(), sku="A-1", name="Widget")
        assert product.is_active is True
        assert product.cost_price == Money.zero("USD")
        assert product.sell_price == Money.zero("USD")
        assert product.reorder_point == Decimal("0")
        assert product.id is None

    def test_money_currency_validation(self) -> None:
        with pytest.raises(ValidationError):
            Product(
                tenant_id=uuid.uuid4(),
                sku="A-1",
                name="Widget",
                cost_price=Money(Decimal("1"), "XYZ"),
            )


class TestWarehouse:
    def test_defaults(self) -> None:
        warehouse = Warehouse(tenant_id=uuid.uuid4(), name="Main")
        assert warehouse.is_active is True
        assert warehouse.location is None
        assert warehouse.id is None


class TestStockLevel:
    def test_defaults(self) -> None:
        level = StockLevel(
            tenant_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            warehouse_id=uuid.uuid4(),
        )
        assert level.qty_on_hand == Decimal("0")
        assert level.qty_reserved == Decimal("0")


class TestStockMovement:
    def test_defaults(self) -> None:
        movement = StockMovement(
            tenant_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            warehouse_id=uuid.uuid4(),
            movement_type=StockMovementType.RECEIPT,
            qty=Decimal("10"),
            ref_type="po",
            ref_id="PO-1",
        )
        assert movement.movement_type is StockMovementType.RECEIPT
        assert movement.id is None
        assert movement.created_at is None
