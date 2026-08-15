"""Canonical audit event keys for the core (ERP) domain.

Single source of truth for the free-form ``action`` strings written to
``audit_logs`` (the shared, identity-owned append-only trail). Services must
reference these constants instead of hardcoding strings so the event
vocabulary stays greppable and drift-checked against the catalog grouping
below — mirroring ``identity.core.audit_events``.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Finance
# ---------------------------------------------------------------------------
FINANCE_CHART_OF_ACCOUNTS_CREATED = "finance.chart_of_accounts.created"
FINANCE_CHART_OF_ACCOUNTS_DEACTIVATED = "finance.chart_of_accounts.deactivated"
FINANCE_JOURNAL_ENTRY_POSTED = "finance.journal_entry.posted"
FINANCE_JOURNAL_ENTRY_VOIDED = "finance.journal_entry.voided"
FINANCE_FISCAL_PERIOD_CREATED = "finance.fiscal_period.created"
FINANCE_FISCAL_PERIOD_CLOSED = "finance.fiscal_period.closed"
FINANCE_INVOICE_CREATED = "finance.invoice.created"
FINANCE_INVOICE_ISSUED = "finance.invoice.issued"
FINANCE_INVOICE_APPROVED = "finance.invoice.approved"
FINANCE_INVOICE_VOIDED = "finance.invoice.voided"
FINANCE_PAYMENT_APPLIED = "finance.payment.applied"

# Every catalogued audit event, in catalog order.
CATALOG: tuple[str, ...] = (
    FINANCE_CHART_OF_ACCOUNTS_CREATED,
    FINANCE_CHART_OF_ACCOUNTS_DEACTIVATED,
    FINANCE_JOURNAL_ENTRY_POSTED,
    FINANCE_JOURNAL_ENTRY_VOIDED,
    FINANCE_FISCAL_PERIOD_CREATED,
    FINANCE_FISCAL_PERIOD_CLOSED,
    FINANCE_INVOICE_CREATED,
    FINANCE_INVOICE_ISSUED,
    FINANCE_INVOICE_APPROVED,
    FINANCE_INVOICE_VOIDED,
    FINANCE_PAYMENT_APPLIED,
)

ALL_AUDIT_EVENTS: frozenset[str] = frozenset(CATALOG)

# Event module groupings (for catalog endpoints and UI).
# Each entry: (module_key, module_label, (event_keys, ...))
AUDIT_EVENT_MODULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "finance",
        "Finance",
        (
            FINANCE_CHART_OF_ACCOUNTS_CREATED,
            FINANCE_CHART_OF_ACCOUNTS_DEACTIVATED,
            FINANCE_JOURNAL_ENTRY_POSTED,
            FINANCE_JOURNAL_ENTRY_VOIDED,
            FINANCE_FISCAL_PERIOD_CREATED,
            FINANCE_FISCAL_PERIOD_CLOSED,
            FINANCE_INVOICE_CREATED,
            FINANCE_INVOICE_ISSUED,
            FINANCE_INVOICE_APPROVED,
            FINANCE_INVOICE_VOIDED,
            FINANCE_PAYMENT_APPLIED,
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
    "FINANCE_CHART_OF_ACCOUNTS_CREATED",
    "FINANCE_CHART_OF_ACCOUNTS_DEACTIVATED",
    "FINANCE_FISCAL_PERIOD_CLOSED",
    "FINANCE_FISCAL_PERIOD_CREATED",
    "FINANCE_INVOICE_APPROVED",
    "FINANCE_INVOICE_CREATED",
    "FINANCE_INVOICE_ISSUED",
    "FINANCE_INVOICE_VOIDED",
    "FINANCE_JOURNAL_ENTRY_POSTED",
    "FINANCE_JOURNAL_ENTRY_VOIDED",
    "FINANCE_PAYMENT_APPLIED",
]
