"""Canonical ERP permission keys for the core service.

Platform-fixed catalog: these keys are the source of truth that role grants
(``core_roles.permissions``) and ``require_permission`` reference. Keys follow
the ``{domain}.{entity}.{action}`` convention (e.g. ``erp.inventory.read``).

A permission must be added here AND via migration before it can be assigned
to roles. Keys reused from identity's catalog (``erp.invoice.read``,
``erp.invoice.approve``, ``erp.purchase.approve``, ``erp.crm.*``,
``erp.sales.*``) are the SAME strings identity seeds, so role grants stay
portable across the platform. The CRM keys and ``erp.sales.approve`` are
seeded into ``core_permissions`` by migration 0003. Inventory keys are
provisional until docs/modules/inventory-warehouse.md lands.
"""

from __future__ import annotations

# Full access within a tenant (owner role).
WILDCARD = "*"

# Inventory (provisional until the inventory-warehouse module doc lands)
ERP_INVENTORY_READ = "erp.inventory.read"
ERP_INVENTORY_WRITE = "erp.inventory.write"
ERP_INVENTORY_ADJUST = "erp.inventory.adjust"
ERP_INVENTORY_ADJUST_APPROVE = "erp.inventory.adjust.approve"

# Purchasing
ERP_PURCHASE_READ = "erp.purchase.read"
ERP_PURCHASE_WRITE = "erp.purchase.write"
ERP_PURCHASE_APPROVE = "erp.purchase.approve"

# CRM (leads, opportunities, customers)
ERP_CRM_READ = "erp.crm.read"
ERP_CRM_WRITE = "erp.crm.write"

# Sales
ERP_SALES_READ = "erp.sales.read"
ERP_SALES_WRITE = "erp.sales.write"
ERP_SALES_APPROVE = "erp.sales.approve"

# Finance / invoicing
ERP_INVOICE_READ = "erp.invoice.read"
ERP_INVOICE_APPROVE = "erp.invoice.approve"
ERP_INVOICE_WRITE = "erp.invoice.write"

# Finance — full ledger/invoice/payment domain (successor to erp.invoice.*).
ERP_FINANCE_READ = "erp.finance.read"
ERP_FINANCE_WRITE = "erp.finance.write"
ERP_FINANCE_APPROVE = "erp.finance.approve"

# Every catalogued permission, in catalog order.
CATALOG: tuple[str, ...] = (
    ERP_INVENTORY_READ,
    ERP_INVENTORY_WRITE,
    ERP_INVENTORY_ADJUST,
    ERP_INVENTORY_ADJUST_APPROVE,
    ERP_PURCHASE_READ,
    ERP_PURCHASE_WRITE,
    ERP_PURCHASE_APPROVE,
    ERP_CRM_READ,
    ERP_CRM_WRITE,
    ERP_SALES_READ,
    ERP_SALES_WRITE,
    ERP_SALES_APPROVE,
    ERP_INVOICE_READ,
    ERP_INVOICE_WRITE,
    ERP_INVOICE_APPROVE,
    ERP_FINANCE_READ,
    ERP_FINANCE_WRITE,
    ERP_FINANCE_APPROVE,
)

# Permission module groupings.
# Each entry: (module_key, module_label, (permission_keys, ...))
PERMISSION_MODULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "inventory",
        "Inventory",
        (
            ERP_INVENTORY_READ,
            ERP_INVENTORY_WRITE,
            ERP_INVENTORY_ADJUST,
            ERP_INVENTORY_ADJUST_APPROVE,
        ),
    ),
    ("purchase", "Purchasing", (ERP_PURCHASE_READ, ERP_PURCHASE_WRITE, ERP_PURCHASE_APPROVE)),
    ("crm", "CRM", (ERP_CRM_READ, ERP_CRM_WRITE)),
    ("sales", "Sales", (ERP_SALES_READ, ERP_SALES_WRITE, ERP_SALES_APPROVE)),
    ("invoice", "Finance / invoicing", (ERP_INVOICE_READ, ERP_INVOICE_WRITE, ERP_INVOICE_APPROVE)),
    ("finance", "Finance", (ERP_FINANCE_READ, ERP_FINANCE_WRITE, ERP_FINANCE_APPROVE)),
)


def _assert_catalog_union() -> None:
    """Ensure PERMISSION_MODULES and CATALOG stay in sync (fail-fast on drift)."""
    module_keys = {k for _, _, keys in PERMISSION_MODULES for k in keys}
    catalog_keys = set(CATALOG)
    if module_keys != catalog_keys:
        missing = catalog_keys - module_keys
        orphaned = module_keys - catalog_keys
        msg = "PERMISSION_MODULES <-> CATALOG mismatch:\n"
        if missing:
            msg += f"  Missing from PERMISSION_MODULES: {missing}\n"
        if orphaned:
            msg += f"  Orphaned in PERMISSION_MODULES: {orphaned}\n"
        raise ValueError(msg)


_assert_catalog_union()

__all__ = [
    "CATALOG",
    "ERP_CRM_READ",
    "ERP_CRM_WRITE",
    "ERP_FINANCE_APPROVE",
    "ERP_FINANCE_READ",
    "ERP_FINANCE_WRITE",
    "ERP_INVENTORY_ADJUST",
    "ERP_INVENTORY_ADJUST_APPROVE",
    "ERP_INVENTORY_READ",
    "ERP_INVENTORY_WRITE",
    "ERP_INVOICE_APPROVE",
    "ERP_INVOICE_READ",
    "ERP_INVOICE_WRITE",
    "ERP_PURCHASE_APPROVE",
    "ERP_PURCHASE_READ",
    "ERP_PURCHASE_WRITE",
    "ERP_SALES_APPROVE",
    "ERP_SALES_READ",
    "ERP_SALES_WRITE",
    "PERMISSION_MODULES",
    "WILDCARD",
]
