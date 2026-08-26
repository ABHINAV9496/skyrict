"""Unit tests for entity name resolution against catalog rows."""

from __future__ import annotations

import uuid

from ai_agent.features.nl_query.gateway import ProductRef, WarehouseRef
from ai_agent.features.nl_query.matcher import resolve_product, resolve_warehouse


def _products() -> list[ProductRef]:
    return [
        ProductRef(
            id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            sku="LAPTOP-CHG-001",
            name="Laptop Charger 65W",
            reorder_point=10,
        ),
        ProductRef(
            id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            sku="LAPTOP-CHG-90W",
            name="Laptop Charger 90W",
            reorder_point=5,
        ),
        ProductRef(
            id=uuid.UUID("00000000-0000-0000-0000-000000000003"),
            sku="KEYB-001",
            name="Mechanical Keyboard",
            reorder_point=8,
        ),
    ]


def _warehouses() -> list[WarehouseRef]:
    return [
        WarehouseRef(id=uuid.UUID("10000000-0000-0000-0000-000000000001"), name="Bangalore"),
        WarehouseRef(id=uuid.UUID("10000000-0000-0000-0000-000000000002"), name="Mumbai"),
    ]


class TestResolveProduct:
    def test_exact_match_case_insensitive(self) -> None:
        match = resolve_product("mechanical keyboard", _products())
        assert match is not None
        assert match.status == "matched"
        assert match.display_name == "Mechanical Keyboard"

    def test_unique_substring_matches(self) -> None:
        match = resolve_product("keyboard", _products())
        assert match is not None
        assert match.status == "matched"
        assert match.display_name == "Mechanical Keyboard"

    def test_ambiguous_substring_returns_ambiguous(self) -> None:
        # "laptop charger" matches two products - never guess.
        match = resolve_product("laptop charger", _products())
        assert match is not None
        assert match.status == "ambiguous"
        assert match.entity_id is None

    def test_unknown_name(self) -> None:
        match = resolve_product("spaceship fuel", _products())
        assert match is not None
        assert match.status == "unknown"
        assert match.entity_id is None

    def test_no_mention_returns_none(self) -> None:
        assert resolve_product(None, _products()) is None


class TestResolveWarehouse:
    def test_exact_match(self) -> None:
        match = resolve_warehouse("Bangalore", _warehouses())
        assert match is not None
        assert match.status == "matched"
        assert str(match.entity_id) == "10000000-0000-0000-0000-000000000001"

    def test_unknown_warehouse(self) -> None:
        match = resolve_warehouse("Atlantis", _warehouses())
        assert match is not None
        assert match.status == "unknown"
