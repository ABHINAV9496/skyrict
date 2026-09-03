"""Unit tests for identity/main.py - application factory wiring.

Covers the SKY-11 docs gating: interactive docs (Swagger UI / ReDoc /
OpenAPI schema) are enabled outside production and disabled in production,
so the public OpenAPI surface is never exposed to attackers.

Middleware order (RequestId -> TenantContext -> CORS) is behaviorally
covered by test_middleware.py; the lifespan lifecycle is covered by
test_readiness.py and the integration suite.
"""

from __future__ import annotations

import pytest

from identity.core.config import Environment, settings
from identity.main import create_app


@pytest.fixture(autouse=True)
def _restore_environment(monkeypatch: pytest.MonkeyPatch):
    """Pin the environment per test; restored automatically by monkeypatch."""
    monkeypatch.setattr(settings, "ENVIRONMENT", Environment.TEST)


class TestDocsGating:
    """Interactive docs are a dev/test convenience, never a production surface."""

    def test_docs_enabled_in_dev(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", Environment.DEV)
        app = create_app()
        assert app.docs_url == "/docs"
        assert app.redoc_url == "/redoc"
        assert app.openapi_url == "/openapi.json"

    def test_docs_enabled_in_test(self):
        app = create_app()
        assert app.docs_url == "/docs"
        assert app.redoc_url == "/redoc"
        assert app.openapi_url == "/openapi.json"

    def test_docs_disabled_in_production(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", Environment.PRODUCTION)
        app = create_app()
        assert app.docs_url is None
        assert app.redoc_url is None
        assert app.openapi_url is None
