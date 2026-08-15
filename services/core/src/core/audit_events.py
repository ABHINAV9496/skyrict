"""Canonical audit event keys for the ERP core domain.

Single source of truth for the free-form ``action`` strings written to the
shared ``audit_logs`` table (append-only, hash-chained — owned by identity's
migration, reused by core). Services must reference these constants instead of
hardcoding strings so the event vocabulary stays greppable and drift-checked
against the catalog grouping below.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
PRODUCT_CREATED = "inventory.product.created"
PRODUCT_UPDATED = "inventory.product.updated"
PRODUCT_DEACTIVATED = "inventory.product.deactivated"
PRODUCT_REACTIVATED = "inventory.product.reactivated"
WAREHOUSE_CREATED = "inventory.warehouse.created"
WAREHOUSE_UPDATED = "inventory.warehouse.updated"
WAREHOUSE_DEACTIVATED = "inventory.warehouse.deactivated"
WAREHOUSE_REACTIVATED = "inventory.warehouse.reactivated"
STOCK_ADJUSTED = "inventory.stock.adjusted"
STOCK_TRANSFERRED = "inventory.stock.transferred"
STOCK_REORDER_ALERTED = "inventory.stock.reorder_alerted"

# Every catalogued audit event, in catalog order.
CATALOG: tuple[str, ...] = (
    PRODUCT_CREATED,
    PRODUCT_UPDATED,
    PRODUCT_DEACTIVATED,
    PRODUCT_REACTIVATED,
    WAREHOUSE_CREATED,
    WAREHOUSE_UPDATED,
    WAREHOUSE_DEACTIVATED,
    WAREHOUSE_REACTIVATED,
    STOCK_ADJUSTED,
    STOCK_TRANSFERRED,
    STOCK_REORDER_ALERTED,
)

ALL_AUDIT_EVENTS: frozenset[str] = frozenset(CATALOG)

# Event module groupings (for catalog endpoints and UI).
# Each entry: (module_key, module_label, (event_keys, ...))
AUDIT_EVENT_MODULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "inventory",
        "Inventory",
        (
            PRODUCT_CREATED,
            PRODUCT_UPDATED,
            PRODUCT_DEACTIVATED,
            PRODUCT_REACTIVATED,
            WAREHOUSE_CREATED,
            WAREHOUSE_UPDATED,
            WAREHOUSE_DEACTIVATED,
            WAREHOUSE_REACTIVATED,
            STOCK_ADJUSTED,
            STOCK_TRANSFERRED,
            STOCK_REORDER_ALERTED,
        ),
    ),
)


def _assert_catalog_union() -> None:
    """Ensure AUDIT_EVENT_MODULES and CATALOG stay in sync (fail-fast on drift)."""
    module_keys = {key for _, _, keys in AUDIT_EVENT_MODULES for key in keys}
    if module_keys != ALL_AUDIT_EVENTS:
        missing = ALL_AUDIT_EVENTS - module_keys
        orphaned = module_keys - ALL_AUDIT_EVENTS
        msg = "AUDIT_EVENT_MODULES <-> CATALOG mismatch:\n"
        if missing:
            msg += f"  Missing from AUDIT_EVENT_MODULES: {sorted(missing)}\n"
        if orphaned:
            msg += f"  Orphaned in AUDIT_EVENT_MODULES: {sorted(orphaned)}\n"
        raise ValueError(msg)


_assert_catalog_union()

__all__ = [
    "ALL_AUDIT_EVENTS",
    "AUDIT_EVENT_MODULES",
    "CATALOG",
    "PRODUCT_CREATED",
    "PRODUCT_DEACTIVATED",
    "PRODUCT_REACTIVATED",
    "PRODUCT_UPDATED",
    "STOCK_ADJUSTED",
    "STOCK_REORDER_ALERTED",
    "STOCK_TRANSFERRED",
    "WAREHOUSE_CREATED",
    "WAREHOUSE_DEACTIVATED",
    "WAREHOUSE_REACTIVATED",
    "WAREHOUSE_UPDATED",
]
