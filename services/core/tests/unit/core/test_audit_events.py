"""Audit event catalog tests — the canonical inventory.* vocabulary.

Guards the single source of truth in ``core.audit_events``: the CATALOG must
stay in sync with AUDIT_EVENT_MODULES (the module-body union assert already
fails fast at import time), every event is namespaced ``inventory.*``, and
``__all__`` re-exports the whole catalog so importers can't silently go stale.
"""

from __future__ import annotations

import core.audit_events as catalog


class TestCatalogShape:
    def test_all_events_are_inventory_namespaced(self) -> None:
        for event in catalog.CATALOG:
            assert event.startswith("inventory.")

    def test_catalog_matches_all_events(self) -> None:
        assert frozenset(catalog.CATALOG) == catalog.ALL_AUDIT_EVENTS

    def test_module_groups_union_equals_catalog(self) -> None:
        module_keys = {key for _, _, keys in catalog.AUDIT_EVENT_MODULES for key in keys}
        assert module_keys == set(catalog.CATALOG)

    def test_expected_events_present(self) -> None:
        expected = {
            "inventory.product.created",
            "inventory.product.updated",
            "inventory.warehouse.created",
            "inventory.stock.adjusted",
            "inventory.stock.transferred",
            "inventory.stock.reorder_alerted",
        }
        assert expected <= set(catalog.CATALOG)

    def test_all_exported(self) -> None:
        for name in catalog.__all__:
            assert hasattr(catalog, name)


class TestConstantsMatchCatalog:
    def test_constants_equal_catalog_entries(self) -> None:
        assert catalog.PRODUCT_CREATED == "inventory.product.created"
        assert catalog.PRODUCT_UPDATED == "inventory.product.updated"
        assert catalog.WAREHOUSE_CREATED == "inventory.warehouse.created"
        assert catalog.STOCK_ADJUSTED == "inventory.stock.adjusted"
        assert catalog.STOCK_TRANSFERRED == "inventory.stock.transferred"
        assert catalog.STOCK_REORDER_ALERTED == "inventory.stock.reorder_alerted"
