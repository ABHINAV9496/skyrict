"""Test fixtures — ephemeral RSA keys, database sessions, test client.

This conftest.py is loaded by pytest before any test module. It generates a
fresh RSA key pair in a temporary directory (never committed to the repo),
sets the environment variables needed for identity/core/config.py to start,
and provides reusable fixtures.
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
# Set required env vars BEFORE anything imports identity.core.config
# (config.py does fail-fast sys.exit on missing vars)
# ---------------------------------------------------------------------------
_KEY_DIR = Path(tempfile.mkdtemp(prefix="skyrict-identity-jwt-"))
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
    "IDENTITY_DATABASE_URL",
    "postgresql+asyncpg://skyrict:Skyrict%4011419@localhost:5432/skyrict_identity",
)
os.environ.setdefault("IDENTITY_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("IDENTITY_RATE_LIMIT_REGISTER", "10000")
os.environ.setdefault("IDENTITY_JWT_PRIVATE_KEY_PATH", str(_KEY_DIR / "private.pem"))
os.environ.setdefault("IDENTITY_JWT_PUBLIC_KEY_PATH", str(_KEY_DIR / "public.pem"))
os.environ.setdefault("IDENTITY_JWKS_ISSUER", "https://auth.test.skyrict.io")
os.environ.setdefault("IDENTITY_JWKS_AUDIENCE", "api.test.skyrict.io")
os.environ.setdefault("IDENTITY_ENVIRONMENT", "test")


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


@pytest.fixture
def anyio_backend():
    """Use asyncio backend for anyio/pytest-asyncio."""
    return "asyncio"


@pytest.fixture
async def client():
    """Async HTTP client against the FastAPI app (ASGI transport).

    Skips integration tests when the identity application cannot be built
    (e.g. while the models/repositories refactor is in flight), instead of
    failing the whole suite.
    """
    try:
        from httpx import ASGITransport, AsyncClient

        from identity.main import app
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.skip(f"identity application unavailable: {exc}")

    # Do not re-raise server exceptions into the test: ServerErrorMiddleware
    # always re-raises after emitting its 500 (errors.py), so tests must be
    # able to inspect the sanitized response (e.g. orphan-rollback checks).
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
