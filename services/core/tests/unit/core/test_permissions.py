"""Permission catalog consistency tests — CATALOG vs PERMISSION_MODULES."""

from __future__ import annotations

from core.core.permissions import (
    CATALOG,
    ERP_INVENTORY_READ,
    ERP_INVOICE_APPROVE,
    ERP_INVOICE_READ,
    ERP_PURCHASE_APPROVE,
    PERMISSION_MODULES,
    WILDCARD,
)


class TestCatalog:
    def test_modules_cover_catalog_exactly(self) -> None:
        module_keys = {key for _, _, keys in PERMISSION_MODULES for key in keys}
        assert module_keys == set(CATALOG)

    def test_catalog_has_no_duplicates(self) -> None:
        assert len(CATALOG) == len(set(CATALOG))

    def test_wildcard_is_platform_constant(self) -> None:
        assert WILDCARD == "*"

    def test_reuses_identity_invoice_keys(self) -> None:
        # identity seeds erp.invoice.read / erp.invoice.approve and
        # erp.purchase.approve — the SAME strings, so role grants stay portable.
        assert ERP_INVOICE_READ == "erp.invoice.read"
        assert ERP_INVOICE_APPROVE == "erp.invoice.approve"
        assert ERP_PURCHASE_APPROVE == "erp.purchase.approve"

    def test_inventory_key_is_provisional(self) -> None:
        # Provisional until docs/modules/inventory-warehouse.md lands.
        assert ERP_INVENTORY_READ == "erp.inventory.read"
