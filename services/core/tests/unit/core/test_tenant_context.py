"""TenantContext tests — request-scoped contextvar lifecycle."""

from __future__ import annotations

import pytest

from core.core.tenant_context import TenantContext, get_current_tenant
from skyrict_common.exceptions import TenantContextMissingError


class TestTenantContext:
    def test_set_and_get(self) -> None:
        TenantContext.set("tenant-1")
        assert TenantContext.get() == "tenant-1"
        TenantContext.reset()

    def test_get_raises_when_unset(self) -> None:
        TenantContext.reset()
        with pytest.raises(TenantContextMissingError):
            TenantContext.get()

    def test_get_optional_when_unset(self) -> None:
        TenantContext.reset()
        assert TenantContext.get_optional() is None

    def test_user_id_roundtrip(self) -> None:
        TenantContext.set("tenant-1")
        TenantContext.set_user_id("user-1")
        assert TenantContext.get_user_id() == "user-1"
        TenantContext.reset()
        assert TenantContext.get_user_id() is None

    def test_roles_permissions_roundtrip(self) -> None:
        TenantContext.set("tenant-1")
        TenantContext.set_roles(["admin"])
        TenantContext.set_permissions(["erp.inventory.read"])
        assert TenantContext.get_roles() == ["admin"]
        assert TenantContext.get_permissions() == ["erp.inventory.read"]
        TenantContext.reset()
        assert TenantContext.get_roles() == []
        assert TenantContext.get_permissions() == []

    def test_get_current_tenant_dependency(self) -> None:
        TenantContext.set("tenant-2")
        assert get_current_tenant(None) == "tenant-2"  # type: ignore[arg-type]
        TenantContext.reset()

    def test_contexts_do_not_leak_across_contextvars(self) -> None:
        TenantContext.set("outer")
        TenantContext.set("inner")
        assert TenantContext.get() == "inner"
        TenantContext.reset()
        with pytest.raises(TenantContextMissingError):
            TenantContext.get()
