"""Unit tests for tenant- and environment-aware security-console URL derivation."""

from __future__ import annotations

import pytest

from identity.core.config import Environment, settings
from identity.core.console_urls import security_console_base_url, security_console_signin_origin


@pytest.mark.parametrize("slug", ["acme", "my-org", None])
def test_dev_derives_tenant_localhost_url(monkeypatch, slug: str | None) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", Environment.DEV)
    monkeypatch.setattr(settings, "SECURITY_CONSOLE_BASE_URL", "")
    monkeypatch.setattr(settings, "SECURITY_CONSOLE_DEV_PORT", 3000)
    monkeypatch.setattr(settings, "BASE_DOMAIN", "")

    if slug is None:
        assert security_console_base_url(tenant_slug=slug) is None
    else:
        assert security_console_base_url(tenant_slug=slug) == f"http://{slug}.localhost:3000"


def test_dev_port_is_configurable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", Environment.DEV)
    monkeypatch.setattr(settings, "SECURITY_CONSOLE_BASE_URL", "")
    monkeypatch.setattr(settings, "SECURITY_CONSOLE_DEV_PORT", 8080)
    monkeypatch.setattr(settings, "BASE_DOMAIN", "")

    assert security_console_base_url(tenant_slug="acme") == "http://acme.localhost:8080"


def test_prod_derives_https_tenant_apex(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", Environment.PRODUCTION)
    monkeypatch.setattr(settings, "SECURITY_CONSOLE_BASE_URL", "")
    monkeypatch.setattr(settings, "BASE_DOMAIN", "skyrict.com")

    assert security_console_base_url(tenant_slug="acme") == "https://acme.skyrict.com"


def test_prod_without_base_domain_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", Environment.PRODUCTION)
    monkeypatch.setattr(settings, "SECURITY_CONSOLE_BASE_URL", "")
    monkeypatch.setattr(settings, "BASE_DOMAIN", "")

    assert security_console_base_url(tenant_slug="acme") is None


def test_staging_derives_https_tenant_apex(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", Environment.STAGING)
    monkeypatch.setattr(settings, "SECURITY_CONSOLE_BASE_URL", "")
    monkeypatch.setattr(settings, "BASE_DOMAIN", "skyrict.com")

    assert security_console_base_url(tenant_slug="acme") == "https://acme.skyrict.com"


def test_override_literal_wins(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", Environment.PRODUCTION)
    monkeypatch.setattr(settings, "SECURITY_CONSOLE_BASE_URL", "https://app.skyrict.io")
    monkeypatch.setattr(settings, "BASE_DOMAIN", "skyrict.com")

    assert security_console_base_url(tenant_slug="acme") == "https://app.skyrict.io"


def test_override_with_slug_placeholder(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", Environment.PRODUCTION)
    monkeypatch.setattr(settings, "SECURITY_CONSOLE_BASE_URL", "https://{slug}.skyrict.io")
    monkeypatch.setattr(settings, "BASE_DOMAIN", "skyrict.com")

    assert security_console_base_url(tenant_slug="acme") == "https://acme.skyrict.io"


def test_signin_origin_dev(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", Environment.DEV)
    monkeypatch.setattr(settings, "SECURITY_CONSOLE_DEV_PORT", 3000)
    monkeypatch.setattr(settings, "BASE_DOMAIN", "")

    assert security_console_signin_origin(tenant_slug="acme") == "http://acme.signin.localhost:3000"
    assert security_console_signin_origin(tenant_slug=None) is None


def test_signin_origin_prod(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", Environment.PRODUCTION)
    monkeypatch.setattr(settings, "BASE_DOMAIN", "skyrict.com")

    assert security_console_signin_origin(tenant_slug="acme") == "https://acme.signin.skyrict.com"


def test_signin_origin_prod_without_base_domain_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", Environment.PRODUCTION)
    monkeypatch.setattr(settings, "BASE_DOMAIN", "")

    assert security_console_signin_origin(tenant_slug="acme") is None
