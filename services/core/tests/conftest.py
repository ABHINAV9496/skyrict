"""Test fixtures - ephemeral RSA keys, environment bootstrap, test client.

This conftest.py is loaded by pytest before any test module. It generates a
fresh RSA key pair in a temporary directory (never committed to the repo),
sets the environment variables needed for core/core/config.py to start, and
provides reusable fixtures.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# ---------------------------------------------------------------------------
# Set required env vars BEFORE anything imports core.core.config
# (config.py does fail-fast sys.exit on missing vars)
# ---------------------------------------------------------------------------
_KEY_DIR = Path(tempfile.mkdtemp(prefix="skyrict-core-jwt-"))
_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
(_KEY_DIR / "private.pem").write_bytes(
    _private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
)
(_KEY_DIR / "public.pem").write_bytes(
    _private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
)

os.environ.setdefault(
    "CORE_DATABASE_URL",
    "postgresql+asyncpg://skyrict:skyrict@localhost:5433/skyrict_identity",
)
os.environ["CORE_JWT_PUBLIC_KEY_PATH"] = str(_KEY_DIR / "public.pem")
os.environ.setdefault("CORE_JWKS_ISSUER", "https://auth.test.skyrict.io")
os.environ.setdefault("CORE_JWKS_AUDIENCE", "api.test.skyrict.io")
# Force the test environment: several branches depend on ENVIRONMENT (e.g.
# production_safety guards and Host-vs-header tenant resolution).
os.environ["CORE_ENVIRONMENT"] = "test"
os.environ["CORE_DEBUG"] = "false"
os.environ["CORE_LOG_JSON"] = "false"


@pytest.fixture(scope="session", autouse=True)
def _cleanup_ephemeral_keys():
    """Remove the generated temp key directory at the end of the session."""
    yield
    shutil.rmtree(_KEY_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def rsa_private_key() -> str:
    """Load the ephemeral RSA private key generated for this test session."""
    return (_KEY_DIR / "private.pem").read_text()


@pytest.fixture(scope="session")
def rsa_public_key() -> str:
    """Load the ephemeral RSA public key generated for this test session."""
    return (_KEY_DIR / "public.pem").read_text()
