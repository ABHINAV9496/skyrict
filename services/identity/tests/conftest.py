"""Test fixtures — RSA keys, database sessions, test client.

This conftest.py is loaded by pytest before any test module. It sets up
the environment variables needed for identity/core/config.py to start
without crashing, and provides reusable fixtures.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Set required env vars BEFORE anything imports identity.core.config
# (config.py does fail-fast sys.exit on missing vars)
# ---------------------------------------------------------------------------
_FIXTURES_DIR = Path(__file__).parent
_RSA_DIR = _FIXTURES_DIR / "fixtures" / "rsa"

os.environ.setdefault("IDENTITY_DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("IDENTITY_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("IDENTITY_JWT_PRIVATE_KEY_PATH", str(_RSA_DIR / "private.pem"))
os.environ.setdefault("IDENTITY_JWT_PUBLIC_KEY_PATH", str(_RSA_DIR / "public.pem"))
os.environ.setdefault("IDENTITY_JWKS_ISSUER", "https://auth.test.skyrict.io")
os.environ.setdefault("IDENTITY_JWKS_AUDIENCE", "api.test.skyrict.io")
os.environ.setdefault("IDENTITY_ENVIRONMENT", "test")


@pytest.fixture(scope="session")
def rsa_private_key() -> str:
    """Load the test RSA private key."""
    return (_RSA_DIR / "private.pem").read_text()


@pytest.fixture(scope="session")
def rsa_public_key() -> str:
    """Load the test RSA public key."""
    return (_RSA_DIR / "public.pem").read_text()


@pytest.fixture
def anyio_backend():
    """Use asyncio backend for anyio/pytest-asyncio."""
    return "asyncio"
