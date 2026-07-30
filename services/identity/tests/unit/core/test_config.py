"""Unit tests for identity/core/config.py — production safety guards.

Covers all three staging/production fail-fast checks:
  1. JWT key paths pointing at committed test fixtures
  2. DEBUG=true
  3. CORS_ORIGINS contains '*'
"""

from __future__ import annotations

from pathlib import Path

import pytest

from identity.core.config import Environment, Settings


def _make_valid_settings(**overrides) -> dict:
    """Return a dict of Settings kwargs that pass load_rsa_keys (valid PEM files)."""
    return {
        "DATABASE_URL": "postgresql+asyncpg://x@localhost/db",
        "REDIS_URL": "redis://localhost:6379/0",
        "JWT_PRIVATE_KEY_PATH": Path("services/identity/tests/fixtures/rsa/private.pem"),
        "JWT_PUBLIC_KEY_PATH": Path("services/identity/tests/fixtures/rsa/public.pem"),
        "JWKS_ISSUER": "https://auth.skyrict.io",
        "JWKS_AUDIENCE": "api.skyrict.io",
        **overrides,
    }


class TestProductionSafety:
    """All three production_safety validator checks."""

    # --- Check 1: test fixture keys ---

    def test_raises_production_fixture_private_key(self):
        with pytest.raises(RuntimeError, match="tests/fixtures"):
            Settings(**_make_valid_settings(
                ENVIRONMENT=Environment.PRODUCTION,
                JWT_PRIVATE_KEY_PATH=Path("services/identity/tests/fixtures/rsa/private.pem"),
            ))

    def test_raises_staging_fixture_public_key(self):
        with pytest.raises(RuntimeError, match="tests/fixtures"):
            Settings(**_make_valid_settings(
                ENVIRONMENT=Environment.STAGING,
                JWT_PUBLIC_KEY_PATH=Path("services/identity/tests/fixtures/rsa/public.pem"),
            ))

    def test_passes_dev_fixture_path(self):
        s = Settings(**_make_valid_settings(ENVIRONMENT=Environment.DEV))
        assert s.ENVIRONMENT == Environment.DEV

    def test_passes_production_real_key_path(self, tmp_path: Path):
        priv = tmp_path / "private.pem"
        pub = tmp_path / "public.pem"
        priv.write_text("-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n")
        pub.write_text("-----BEGIN PUBLIC KEY-----\nfake\n-----END PUBLIC KEY-----\n")
        s = Settings(**_make_valid_settings(
            ENVIRONMENT=Environment.PRODUCTION,
            JWT_PRIVATE_KEY_PATH=priv,
            JWT_PUBLIC_KEY_PATH=pub,
        ))
        assert s.ENVIRONMENT == Environment.PRODUCTION

    # --- Check 2: DEBUG=true ---

    def test_raises_production_debug_true(self):
        with pytest.raises(RuntimeError, match="DEBUG=true is not allowed"):
            Settings(**_make_valid_settings(
                ENVIRONMENT=Environment.PRODUCTION,
                DEBUG=True,
            ))

    def test_raises_staging_debug_true(self):
        with pytest.raises(RuntimeError, match="DEBUG=true is not allowed"):
            Settings(**_make_valid_settings(
                ENVIRONMENT=Environment.STAGING,
                DEBUG=True,
            ))

    def test_passes_dev_debug_true(self):
        s = Settings(**_make_valid_settings(ENVIRONMENT=Environment.DEV, DEBUG=True))
        assert s.DEBUG is True

    def test_passes_production_debug_false(self, tmp_path: Path):
        priv = tmp_path / "private.pem"
        pub = tmp_path / "public.pem"
        priv.write_text("-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n")
        pub.write_text("-----BEGIN PUBLIC KEY-----\nfake\n-----END PUBLIC KEY-----\n")
        s = Settings(**_make_valid_settings(
            ENVIRONMENT=Environment.PRODUCTION,
            DEBUG=False,
            JWT_PRIVATE_KEY_PATH=priv,
            JWT_PUBLIC_KEY_PATH=pub,
        ))
        assert s.DEBUG is False

    # --- Check 3: wildcard CORS ---

    def test_raises_production_wildcard_cors(self, tmp_path: Path):
        priv = tmp_path / "private.pem"
        pub = tmp_path / "public.pem"
        priv.write_text("-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n")
        pub.write_text("-----BEGIN PUBLIC KEY-----\nfake\n-----END PUBLIC KEY-----\n")
        with pytest.raises(RuntimeError, match="CORS_ORIGINS contains"):
            Settings(**_make_valid_settings(
                ENVIRONMENT=Environment.PRODUCTION,
                CORS_ORIGINS=["*"],
                JWT_PRIVATE_KEY_PATH=priv,
                JWT_PUBLIC_KEY_PATH=pub,
            ))

    def test_raises_staging_wildcard_cors(self, tmp_path: Path):
        priv = tmp_path / "private.pem"
        pub = tmp_path / "public.pem"
        priv.write_text("-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n")
        pub.write_text("-----BEGIN PUBLIC KEY-----\nfake\n-----END PUBLIC KEY-----\n")
        with pytest.raises(RuntimeError, match="CORS_ORIGINS contains"):
            Settings(**_make_valid_settings(
                ENVIRONMENT=Environment.STAGING,
                CORS_ORIGINS=["*"],
                JWT_PRIVATE_KEY_PATH=priv,
                JWT_PUBLIC_KEY_PATH=pub,
            ))

    def test_passes_dev_wildcard_cors(self):
        s = Settings(**_make_valid_settings(ENVIRONMENT=Environment.DEV, CORS_ORIGINS=["*"]))
        assert "*" in s.CORS_ORIGINS

    def test_passes_production_explicit_cors(self, tmp_path: Path):
        priv = tmp_path / "private.pem"
        pub = tmp_path / "public.pem"
        priv.write_text("-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n")
        pub.write_text("-----BEGIN PUBLIC KEY-----\nfake\n-----END PUBLIC KEY-----\n")
        s = Settings(**_make_valid_settings(
            ENVIRONMENT=Environment.PRODUCTION,
            CORS_ORIGINS=["https://app.skyrict.io"],
            JWT_PRIVATE_KEY_PATH=priv,
            JWT_PUBLIC_KEY_PATH=pub,
        ))
        assert "https://app.skyrict.io" in s.CORS_ORIGINS


class TestEnvironmentEnum:
    """Verify Environment StrEnum works correctly."""

    def test_enum_values(self):
        assert Environment.DEV.value == "dev"
        assert Environment.TEST.value == "test"
        assert Environment.STAGING.value == "staging"
        assert Environment.PRODUCTION.value == "production"

    def test_string_comparison(self):
        assert Environment.DEV == "dev"
        assert Environment.PRODUCTION == "production"

    def test_settings_default_is_dev(self, tmp_path: Path):
        priv = tmp_path / "private.pem"
        pub = tmp_path / "public.pem"
        priv.write_text("-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n")
        pub.write_text("-----BEGIN PUBLIC KEY-----\nfake\n-----END PUBLIC KEY-----\n")
        s = Settings(**_make_valid_settings(
            JWT_PRIVATE_KEY_PATH=priv,
            JWT_PUBLIC_KEY_PATH=pub,
        ))
        assert s.ENVIRONMENT == Environment.DEV
