"""TenantResolver tests — Host-subdomain (prod) and X-Tenant-Slug (dev) routing."""

from __future__ import annotations

from core.core.tenant_resolver import TenantResolver

RESOLVER = TenantResolver(base_domain="skyrict.com")


class TestResolveFromHost:
    def test_subdomain_derived(self) -> None:
        assert RESOLVER.resolve_from_host("olympus.skyrict.com") == "olympus"

    def test_nested_subdomain_uses_first_label(self) -> None:
        assert RESOLVER.resolve_from_host("a.b.skyrict.com") == "a"

    def test_apex_is_not_a_tenant(self) -> None:
        assert RESOLVER.resolve_from_host("skyrict.com") is None

    def test_unrelated_domain_is_not_a_tenant(self) -> None:
        assert RESOLVER.resolve_from_host("acme.evil.com") is None

    def test_reserved_slug_rejected(self) -> None:
        assert RESOLVER.resolve_from_host("www.skyrict.com") is None
        assert RESOLVER.resolve_from_host("admin.skyrict.com") is None

    def test_invalid_slug_grammar_rejected(self) -> None:
        assert RESOLVER.resolve_from_host("under_score.skyrict.com") is None

    def test_port_stripped(self) -> None:
        assert RESOLVER.resolve_from_host("olympus.skyrict.com:443") == "olympus"

    def test_empty_host(self) -> None:
        assert RESOLVER.resolve_from_host("") is None


class TestResolveFromHeader:
    def test_header_slug_used(self) -> None:
        assert RESOLVER.resolve_from_header("Olympus") == "olympus"

    def test_header_reserved_slug_rejected(self) -> None:
        assert RESOLVER.resolve_from_header("www") is None

    def test_header_empty_rejected(self) -> None:
        assert RESOLVER.resolve_from_header("") is None
        assert RESOLVER.resolve_from_header(None) is None

    def test_header_invalid_grammar_rejected(self) -> None:
        assert RESOLVER.resolve_from_header("under_score") is None
