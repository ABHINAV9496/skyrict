"""Unit tests for TenantContext - ContextVar isolation and lifecycle.

Proves the request-scoped contract:
  - get() raises when the context is not set (never silently defaults)
  - set/reset round-trips all four fields (tenant_id, user_id, roles, permissions)
  - no leakage across sequential or concurrent async requests
"""

from __future__ import annotations

import asyncio

import pytest

from identity.core.exceptions import TenantContextMissingError
from identity.core.tenant_context import TenantContext


class TestTenantContext:
    def test_get_raises_when_unset(self):
        TenantContext.reset()
        with pytest.raises(TenantContextMissingError):
            TenantContext.get()

    def test_set_and_get_roundtrip(self):
        TenantContext.reset()
        TenantContext.set("tenant-acme")
        assert TenantContext.get() == "tenant-acme"

    def test_get_optional_is_none_when_unset(self):
        TenantContext.reset()
        assert TenantContext.get_optional() is None

    def test_get_optional_returns_tenant_when_set(self):
        TenantContext.reset()
        TenantContext.set("tenant-acme")
        assert TenantContext.get_optional() == "tenant-acme"

    def test_user_id_roundtrip(self):
        TenantContext.reset()
        TenantContext.set("tenant-acme")
        TenantContext.set_user_id("user-1")
        assert TenantContext.get_user_id() == "user-1"

    def test_user_id_defaults_to_none(self):
        TenantContext.reset()
        assert TenantContext.get_user_id() is None

    def test_roles_default_empty(self):
        TenantContext.reset()
        assert TenantContext.get_roles() == []

    def test_roles_roundtrip(self):
        TenantContext.reset()
        TenantContext.set_roles(["owner", "admin"])
        assert TenantContext.get_roles() == ["owner", "admin"]

    def test_permissions_default_empty(self):
        TenantContext.reset()
        assert TenantContext.get_permissions() == []

    def test_permissions_roundtrip(self):
        TenantContext.reset()
        TenantContext.set_permissions(["users:read", "users:write"])
        assert TenantContext.get_permissions() == ["users:read", "users:write"]

    def test_reset_clears_all_fields(self):
        TenantContext.reset()
        TenantContext.set("tenant-acme")
        TenantContext.set_user_id("user-1")
        TenantContext.set_roles(["admin"])
        TenantContext.set_permissions(["users:read"])

        TenantContext.reset()

        with pytest.raises(TenantContextMissingError):
            TenantContext.get()
        assert TenantContext.get_user_id() is None
        assert TenantContext.get_roles() == []
        assert TenantContext.get_permissions() == []

    def test_accessors_return_copies(self):
        TenantContext.reset()
        TenantContext.set_roles(["owner"])
        roles = TenantContext.get_roles()
        roles.append("mutated")
        assert TenantContext.get_roles() == ["owner"]


class TestTenantContextIsolation:
    def test_no_leakage_across_sequential_requests(self):
        # Request 1
        TenantContext.set("tenant-a")
        TenantContext.set_user_id("user-a")
        assert TenantContext.get() == "tenant-a"
        TenantContext.reset()

        # Request 2 - must NOT see request 1's tenant
        with pytest.raises(TenantContextMissingError):
            TenantContext.get()

    async def test_no_leakage_across_concurrent_requests(self):
        """ContextVars isolate concurrent async tasks; reset prevents bleed."""

        async def handle_request(tenant: str, user: str) -> None:
            TenantContext.set(tenant)
            TenantContext.set_user_id(user)
            TenantContext.set_roles([tenant])
            await asyncio.sleep(0)  # yield so the other task runs concurrently
            assert TenantContext.get() == tenant
            assert TenantContext.get_user_id() == user
            assert TenantContext.get_roles() == [tenant]
            TenantContext.reset()

        await asyncio.gather(handle_request("acme", "user-1"), handle_request("globex", "user-2"))

        # After both tasks complete, the context must be empty in the caller.
        assert TenantContext.get_optional() is None
