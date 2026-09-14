"""Unit tests for the notification category registry (SKY-93).

The registry is the platform-fixed catalog; these tests lock the invariants
the preferences page and the batching policy depend on:
every category has a label and a module; the compliance category is the one
mandatory, non-opt-out category; the relevance permissions resolve through
the exact ERP keys that exist in core.core.permissions.
"""

from __future__ import annotations

from core.core.permissions import (
    ERP_FINANCE_APPROVE,
    ERP_FINANCE_READ,
    ERP_INVENTORY_READ,
    ERP_PAYROLL_READ,
)
from core.features.notifications.categories import (
    CATEGORIES,
    category_labels,
    get_category,
    mandatory_categories,
)

RELEVANCE_PERMISSIONS = {
    "inventory": ERP_INVENTORY_READ,
    "finance": ERP_FINANCE_READ,
    "approval": ERP_FINANCE_APPROVE,
    "payroll": ERP_PAYROLL_READ,
}


class TestCategoryRegistry:
    def test_registry_is_non_empty_and_stable(self) -> None:
        assert set(CATEGORIES) == {
            "inventory",
            "finance",
            "approval",
            "compliance",
            "payroll",
            "anomaly",
            "product",
        }

    def test_every_category_has_label_and_module(self) -> None:
        for spec in CATEGORIES.values():
            assert spec.label.strip()
            assert spec.module.strip()

    def test_only_compliance_is_mandatory(self) -> None:
        assert mandatory_categories() == frozenset({"compliance"})
        assert CATEGORIES["compliance"].mandatory
        assert not any(spec.mandatory for key, spec in CATEGORIES.items() if key != "compliance")

    def test_relevance_permissions_match_core_keys(self) -> None:
        for key, perm in RELEVANCE_PERMISSIONS.items():
            assert CATEGORIES[key].relevance_permission == perm

    def test_anomaly_and_product_have_no_relevance_permission(self) -> None:
        assert CATEGORIES["anomaly"].relevance_permission is None
        assert CATEGORIES["product"].relevance_permission is None

    def test_defaults_are_in_app_on_email_webhook_off(self) -> None:
        for spec in CATEGORIES.values():
            assert spec.default_in_app
            assert not spec.default_email
            assert not spec.default_webhook

    def test_get_category_returns_none_for_unknown(self) -> None:
        assert get_category("nope") is None
        assert get_category("finance") is not None

    def test_category_labels_cover_registry(self) -> None:
        labels = category_labels()
        assert labels["compliance"] == "Compliance"
        assert set(labels) == set(CATEGORIES)

    def test_registry_is_the_single_audience_source(self) -> None:
        # Guard against accidental duplicate categories with the same key.
        assert len(CATEGORIES) == len({spec.key for spec in CATEGORIES.values()})
