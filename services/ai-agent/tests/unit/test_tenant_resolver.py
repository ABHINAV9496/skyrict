"""Unit tests for tenant slug resolution (routing contract)."""

from __future__ import annotations

import pytest

from ai_agent.core.config import Environment
from ai_agent.core.tenant_resolver import TenantResolver


class TestResolveFromHost:
    def test_first_label_is_slug(self) -> None:
        # "olympus" is not in RESERVED_SLUGS (platform hosts like www/api/app).
        resolver = TenantResolver(base_domain="skyrict.com")

        assert resolver.resolve_from_host("olympus.skyrict.com") == "olympus"

    def test_apex_is_not_a_tenant(self) -> None:
        resolver = TenantResolver(base_domain="skyrict.com")

        assert resolver.resolve_from_host("skyrict.com") is None

    def test_reserved_slug_rejected(self) -> None:
        resolver = TenantResolver(base_domain="skyrict.com", reserved_slugs=frozenset({"api"}))

        assert resolver.resolve_from_host("api.skyrict.com") is None

    def test_port_stripped(self) -> None:
        resolver = TenantResolver(base_domain="skyrict.com")

        assert resolver.resolve_from_host("olympus.skyrict.com:443") == "olympus"

    def test_invalid_grammar_rejected(self) -> None:
        resolver = TenantResolver(base_domain="skyrict.com")

        assert resolver.resolve_from_host("ACME.skyrict.com") is None


class TestResolveFromHeader:
    def test_valid_header_accepted(self) -> None:
        resolver = TenantResolver(base_domain="")

        assert resolver.resolve_from_header("olympus") == "olympus"

    def test_invalid_header_rejected(self) -> None:
        resolver = TenantResolver(base_domain="")

        assert resolver.resolve_from_header("NOT VALID!") is None
        assert resolver.resolve_from_header(None) is None


@pytest.mark.parametrize(
    ("environment", "expected_source"),
    [
        (Environment.STAGING, "host"),
        (Environment.PRODUCTION, "host"),
        (Environment.DEV, "header"),
        (Environment.TEST, "header"),
    ],
)
def test_environment_selects_routing_source(monkeypatch, environment, expected_source) -> None:
    from ai_agent.core import tenant_resolver

    monkeypatch.setattr(tenant_resolver.settings, "ENVIRONMENT", environment)

    class _FakeRequest:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

    request = _FakeRequest()
    if expected_source == "header":
        request.headers["X-Tenant-Slug"] = "olympus"
    else:
        request.headers["host"] = "olympus.skyrict.com"

    resolver = tenant_resolver.TenantResolver(base_domain="skyrict.com")
    assert resolver.resolve(request) == "olympus"  # type: ignore[arg-type]
