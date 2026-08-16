"""Audit event catalog consistency tests.

Two catalogs coexist in the merged tree: ``core.core.audit_events`` holds the
HR/payroll/finance vocabulary, and ``core.audit_events`` holds the shared
feature catalog (inventory + CRM + sales). Each file guards its own catalog's
CATALOG <-> AUDIT_EVENT_MODULES consistency and canonical vocabulary.
"""

from __future__ import annotations

import core.audit_events as inventory_catalog
from core.core.audit_events import (
    AUDIT_EVENT_MODULES,
    CATALOG,
    HR_LEAVE_APPROVED,
    PAYROLL_RUN_APPROVED,
)


class TestAuditEventCatalog:
    def test_modules_cover_catalog_exactly(self) -> None:
        module_keys = {key for _, _, keys in AUDIT_EVENT_MODULES for key in keys}
        assert module_keys == set(CATALOG)

    def test_catalog_has_no_duplicates(self) -> None:
        assert len(CATALOG) == len(set(CATALOG))

    def test_hr_payroll_events_follow_doc_vocabulary(self) -> None:
        # docs/modules/hr-payroll.md step 4 canonical vocabulary.
        assert HR_LEAVE_APPROVED == "hr.leave.approved"
        assert PAYROLL_RUN_APPROVED == "payroll.run.approved"
        assert "hr.department.created" in CATALOG
        assert "payroll.settings.updated" in CATALOG


class TestInventoryCatalogShape:
    def test_all_events_are_feature_namespaced(self) -> None:
        module_namespaces = {key for key, _, _ in inventory_catalog.AUDIT_EVENT_MODULES}
        for event in inventory_catalog.CATALOG:
            assert event.split(".", 1)[0] in module_namespaces

    def test_catalog_matches_all_events(self) -> None:
        assert frozenset(inventory_catalog.CATALOG) == inventory_catalog.ALL_AUDIT_EVENTS

    def test_module_groups_union_equals_catalog(self) -> None:
        module_keys = {key for _, _, keys in inventory_catalog.AUDIT_EVENT_MODULES for key in keys}
        assert module_keys == set(inventory_catalog.CATALOG)

    def test_expected_events_present(self) -> None:
        expected = {
            "inventory.product.created",
            "inventory.product.updated",
            "inventory.warehouse.created",
            "inventory.stock.adjusted",
            "inventory.stock.transferred",
            "inventory.stock.reorder_alerted",
        }
        assert expected <= set(inventory_catalog.CATALOG)

    def test_all_exported(self) -> None:
        for name in inventory_catalog.__all__:
            assert hasattr(inventory_catalog, name)


class TestInventoryConstantsMatchCatalog:
    def test_constants_equal_catalog_entries(self) -> None:
        assert inventory_catalog.PRODUCT_CREATED == "inventory.product.created"
        assert inventory_catalog.PRODUCT_UPDATED == "inventory.product.updated"
        assert inventory_catalog.WAREHOUSE_CREATED == "inventory.warehouse.created"
        assert inventory_catalog.STOCK_ADJUSTED == "inventory.stock.adjusted"
        assert inventory_catalog.STOCK_TRANSFERRED == "inventory.stock.transferred"
        assert inventory_catalog.STOCK_REORDER_ALERTED == "inventory.stock.reorder_alerted"
