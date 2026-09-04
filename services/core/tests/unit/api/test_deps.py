"""API dependency logic tests - permission grant resolution (pure functions).

``require_permission`` resolves grants from the database at request time; the
DB-backed join (RbacRepository) is covered by the integration suite. Here we
test the pure resolution contract ``grants_permission`` that both depend on.
"""

from __future__ import annotations

from core.db.rbac import grants_permission


class TestGrantsPermission:
    def test_exact_match_grants(self) -> None:
        assert grants_permission(["erp.inventory.read"], "erp.inventory.read")

    def test_wildcard_grants_everything(self) -> None:
        assert grants_permission(["*"], "erp.invoice.approve")

    def test_unrelated_grant_denies(self) -> None:
        assert not grants_permission(["erp.inventory.read"], "erp.invoice.approve")

    def test_empty_grants_deny(self) -> None:
        assert not grants_permission([], "erp.invoice.read")

    def test_fails_closed_on_partial_prefix(self) -> None:
        # "erp.inventory" must NOT grant "erp.inventory.adjust" - exact keys only.
        assert not grants_permission(["erp.inventory"], "erp.inventory.adjust")

    def test_owner_grant_list(self) -> None:
        assert grants_permission(["*", "erp.inventory.read"], "erp.purchase.approve")
