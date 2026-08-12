"""Config tests — CORE_ prefix, defaults, and production-safety guards."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.core.config import Environment, Settings, settings


class TestSettings:
    def test_environment_forced_to_test(self) -> None:
        assert settings.ENVIRONMENT is Environment.TEST
        assert settings.DEBUG is False

    def test_default_currency_default(self) -> None:
        assert settings.DEFAULT_CURRENCY == "USD"

    def test_inventory_threshold_default(self) -> None:
        assert Decimal("100.00") == settings.INVENTORY_ADJUST_APPROVE_THRESHOLD

    def test_public_key_loaded_from_path(self) -> None:
        assert "PUBLIC KEY" in settings.jwt_public_key


class TestProductionSafety:
    @pytest.fixture
    def prod_env(self, monkeypatch) -> None:
        monkeypatch.setenv("CORE_ENVIRONMENT", "production")
        monkeypatch.setenv("CORE_BASE_DOMAIN", "skyrict.com")
        monkeypatch.delenv("CORE_DEBUG", raising=False)

    def test_production_requires_base_domain(self, monkeypatch) -> None:
        monkeypatch.setenv("CORE_ENVIRONMENT", "production")
        monkeypatch.delenv("CORE_BASE_DOMAIN", raising=False)
        with pytest.raises(RuntimeError, match="BASE_DOMAIN"):
            Settings()

    def test_production_rejects_debug(self, monkeypatch) -> None:
        monkeypatch.setenv("CORE_ENVIRONMENT", "production")
        monkeypatch.setenv("CORE_BASE_DOMAIN", "skyrict.com")
        monkeypatch.setenv("CORE_DEBUG", "true")
        with pytest.raises(RuntimeError, match="DEBUG"):
            Settings()

    def test_production_rejects_wildcard_cors(self, prod_env, monkeypatch) -> None:
        monkeypatch.setenv("CORE_CORS_ORIGINS", '["*"]')
        with pytest.raises(RuntimeError, match="CORS"):
            Settings()

    def test_production_accepts_explicit_origins(self, prod_env, monkeypatch) -> None:
        monkeypatch.setenv("CORE_CORS_ORIGINS", '["https://app.skyrict.com"]')
        instance = Settings()
        assert instance.CORS_ORIGINS == ["https://app.skyrict.com"]
