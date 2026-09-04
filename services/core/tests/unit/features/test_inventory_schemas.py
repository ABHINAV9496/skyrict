"""Inventory schema tests - the HTTP boundary (requests and responses).

Money is a pure-domain value object, so inputs carry ``(amount, currency)``
tuples and outputs serialize amounts as strings (JSON never loses precision).
Covers: money conversion helpers, request validation constraints, and
``from_entity`` response building for every response model.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError

from core.domain.entities import Product, StockLevel, StockMovement, Warehouse
from core.domain.value_objects import Money, StockMovementType
from core.features.inventory.schemas import (
    AlertResponse,
    ProductCreate,
    ProductResponse,
    StockAdjustmentCreate,
    StockLevelResponse,
    StockMovementResponse,
    StockTransferCreate,
    TransferResponse,
    WarehouseCreate,
    WarehouseResponse,
    money_input,
    money_output,
)

_TENANT = uuid.uuid4()
_PRODUCT_ID = uuid.uuid4()
_WAREHOUSE_ID = uuid.uuid4()
_NOW = datetime.now(UTC)


def _product(**overrides: object) -> Product:
    defaults: dict[str, object] = {
        "tenant_id": _TENANT,
        "sku": "SKU-1",
        "name": "Widget",
        "cost_price": Money(Decimal("12.50"), "USD"),
        "sell_price": Money(Decimal("19.99"), "USD"),
        "reorder_point": Decimal("5.00"),
        "id": _PRODUCT_ID,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Product(**defaults)


def _warehouse(**overrides: object) -> Warehouse:
    defaults: dict[str, object] = {
        "tenant_id": _TENANT,
        "name": "Main",
        "location": "A1",
        "id": _WAREHOUSE_ID,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Warehouse(**defaults)


def _level(**overrides: object) -> StockLevel:
    defaults: dict[str, object] = {
        "tenant_id": _TENANT,
        "product_id": _PRODUCT_ID,
        "warehouse_id": _WAREHOUSE_ID,
        "qty_on_hand": Decimal("10.000"),
        "qty_reserved": Decimal("3.000"),
        "id": uuid.uuid4(),
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return StockLevel(**defaults)


def _movement(**overrides: object) -> StockMovement:
    defaults: dict[str, object] = {
        "tenant_id": _TENANT,
        "product_id": _PRODUCT_ID,
        "warehouse_id": _WAREHOUSE_ID,
        "movement_type": StockMovementType.ADJUSTMENT,
        "qty": Decimal("-4.50"),
        "ref_type": "adjustment",
        "ref_id": "ADJ-1",
        "id": uuid.uuid4(),
        "created_at": _NOW,
    }
    defaults.update(overrides)
    return StockMovement(**defaults)


class TestMoneyHelpers:
    def test_money_input_from_tuple(self) -> None:
        money = money_input((Decimal("12.50"), "USD"))
        assert money.amount == Decimal("12.50")
        assert money.currency == "USD"

    def test_money_input_none_uses_default_currency(self) -> None:
        money = money_input(None)
        assert money.amount == 0
        assert money.currency == "USD"

    def test_money_output_serializes_exact_decimals_as_strings(self) -> None:
        amount, currency = money_output(Money(Decimal("0.010"), "EUR"))
        assert amount == "0.010"
        assert currency == "EUR"
        assert isinstance(amount, str)


class TestProductSchemas:
    def test_product_create_accepts_valid_body(self) -> None:
        body = ProductCreate(
            sku="SKU-1",
            name="Widget",
            cost_price=(Decimal("12.50"), "USD"),
            reorder_point=Decimal("5"),
        )
        assert body.sku == "SKU-1"
        assert body.cost_price == (Decimal("12.50"), "USD")

    def test_product_create_rejects_blank_sku(self) -> None:
        with pytest.raises(PydanticValidationError):
            ProductCreate(sku="", name="Widget")

    def test_product_create_rejects_negative_reorder_point(self) -> None:
        with pytest.raises(PydanticValidationError):
            ProductCreate(sku="SKU-1", name="Widget", reorder_point=Decimal("-1"))

    def test_product_response_from_entity(self) -> None:
        response = ProductResponse.from_entity(_product())
        assert response.id == _PRODUCT_ID
        assert response.sku == "SKU-1"
        assert response.cost_price == ("12.50", "USD")
        assert response.sell_price == ("19.99", "USD")
        assert response.reorder_point == "5.00"
        assert response.is_active is True
        assert response.created_at == _NOW

    def test_product_response_from_entity_requires_id(self) -> None:
        with pytest.raises(AssertionError):
            ProductResponse.from_entity(_product(id=None, created_at=None, updated_at=None))


class TestWarehouseSchemas:
    def test_warehouse_create_accepts_valid_body(self) -> None:
        body = WarehouseCreate(name="Main", location="A1")
        assert body.name == "Main"
        assert body.location == "A1"

    def test_warehouse_create_rejects_blank_name(self) -> None:
        with pytest.raises(PydanticValidationError):
            WarehouseCreate(name="")

    def test_warehouse_response_from_entity(self) -> None:
        response = WarehouseResponse.from_entity(_warehouse())
        assert response.id == _WAREHOUSE_ID
        assert response.name == "Main"
        assert response.location == "A1"
        assert response.is_active is True


class TestStockSchemas:
    def test_adjustment_accepts_signed_qty_with_reason(self) -> None:
        body = StockAdjustmentCreate(
            product_id=_PRODUCT_ID,
            warehouse_id=_WAREHOUSE_ID,
            qty=Decimal("-3"),
            reason="damage",
            ref_id="ADJ-1",
        )
        assert body.qty == Decimal("-3")

    def test_adjustment_requires_reason(self) -> None:
        with pytest.raises(PydanticValidationError):
            StockAdjustmentCreate(
                product_id=_PRODUCT_ID,
                warehouse_id=_WAREHOUSE_ID,
                qty=Decimal("3"),
                reason="",
                ref_id="ADJ-1",
            )

    def test_transfer_requires_positive_qty(self) -> None:
        with pytest.raises(PydanticValidationError):
            StockTransferCreate(
                product_id=_PRODUCT_ID,
                from_warehouse_id=uuid.uuid4(),
                to_warehouse_id=uuid.uuid4(),
                qty=Decimal("0"),
                ref_id="TR-1",
            )

    def test_stock_level_response_serializes_quantities_as_strings(self) -> None:
        response = StockLevelResponse.from_entity(_level())
        assert response.qty_on_hand == "10.000"
        assert response.qty_reserved == "3.000"
        assert response.product_id == _PRODUCT_ID
        assert response.warehouse_id == _WAREHOUSE_ID

    def test_movement_response_round_trips_signed_qty(self) -> None:
        response = StockMovementResponse.from_entity(_movement())
        assert response.qty == "-4.50"
        assert response.movement_type is StockMovementType.ADJUSTMENT
        assert response.ref_type == "adjustment"
        assert response.ref_id == "ADJ-1"

    def test_transfer_response_holds_both_movements(self) -> None:
        out = _movement(qty=Decimal("-4"), ref_id="TR-1")
        incoming = _movement(qty=Decimal("4"), ref_id="TR-1", warehouse_id=uuid.uuid4())
        response = TransferResponse.from_entities(out, incoming)
        assert response.from_movement.qty == "-4"
        assert response.to_movement.qty == "4"
        assert response.from_movement.ref_id == response.to_movement.ref_id == "TR-1"

    def test_alert_response_from_level_and_product(self) -> None:
        response = AlertResponse.from_entities(_level(), _product(reorder_point=Decimal("10")))
        assert response.sku == "SKU-1"
        assert response.qty_on_hand == "10.000"
        assert response.reorder_point == "10"
