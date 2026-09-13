"""Notification category registry (SKY-93) - the platform-fixed catalog.

A category is a named, labelled family of notifications grouped per producing
module. The registry is the single source of truth for:

- the category's display label (used by the drawer and preferences page),
- the owning module (drives burst grouping in the batching worker),
- the relevance permission (users holding it are the natural audience and
  receive the role-relevance scoring boost),
- whether the category is MANDATORY (compliance): these can never be
  collapsed into a digest, snoozed, or opted out of server-side - the
  ``in_app`` channel is forced on regardless of preferences.

Adding a category here is all a new producer needs; the preferences page
renders the union of this registry and the user's stored rows.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.core.permissions import (
    ERP_FINANCE_APPROVE,
    ERP_FINANCE_READ,
    ERP_INVENTORY_READ,
    ERP_PAYROLL_READ,
)


@dataclass(frozen=True)
class NotificationCategorySpec:
    """Static metadata for one notification category."""

    key: str
    label: str
    module: str
    mandatory: bool = False
    relevance_permission: str | None = None
    default_in_app: bool = True
    default_email: bool = False
    default_webhook: bool = False


CATEGORIES: dict[str, NotificationCategorySpec] = {
    "inventory": NotificationCategorySpec(
        key="inventory",
        label="Inventory",
        module="inventory",
        relevance_permission=ERP_INVENTORY_READ,
    ),
    "finance": NotificationCategorySpec(
        key="finance",
        label="Finance",
        module="finance",
        relevance_permission=ERP_FINANCE_READ,
    ),
    "approval": NotificationCategorySpec(
        key="approval",
        label="Approvals",
        module="approval",
        relevance_permission=ERP_FINANCE_APPROVE,
    ),
    "compliance": NotificationCategorySpec(
        key="compliance",
        label="Compliance",
        module="compliance",
        mandatory=True,
    ),
    "payroll": NotificationCategorySpec(
        key="payroll",
        label="Payroll",
        module="payroll",
        relevance_permission=ERP_PAYROLL_READ,
    ),
    "anomaly": NotificationCategorySpec(
        key="anomaly",
        label="Anomalies",
        module="ai",
    ),
    "product": NotificationCategorySpec(
        key="product",
        label="Product",
        module="product",
    ),
}


def get_category(key: str) -> NotificationCategorySpec | None:
    """Return the category spec, or ``None`` when the key is not registered."""
    return CATEGORIES.get(key)


def mandatory_categories() -> frozenset[str]:
    """Keys of every mandatory category (compliance-style, non-opt-out)."""
    return frozenset(key for key, spec in CATEGORIES.items() if spec.mandatory)


def category_labels() -> dict[str, str]:
    """key -> display label for the whole registry (preferences rendering)."""
    return {key: spec.label for key, spec in CATEGORIES.items()}
