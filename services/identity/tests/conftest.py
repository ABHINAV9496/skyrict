from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

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
os.environ.setdefault("IDENTITY_SIGNUP_START_RATE_LIMIT", "10000")
os.environ.setdefault("IDENTITY_SIGNUP_CODE_RATE_LIMIT", "10000")
os.environ.setdefault("IDENTITY_SIGNUP_VERIFY_RATE_LIMIT", "10000")
os.environ.setdefault("IDENTITY_SIGNUP_CHECK_RATE_LIMIT", "10000")


os.environ.setdefault("IDENTITY_RATE_LIMIT_LOGIN_IP", "10000")
os.environ.setdefault("IDENTITY_RATE_LIMIT_MFA_VERIFY", "10000")
os.environ.setdefault("IDENTITY_JWT_PRIVATE_KEY_PATH", str(_KEY_DIR / "private.pem"))
os.environ.setdefault("IDENTITY_JWT_PUBLIC_KEY_PATH", str(_KEY_DIR / "public.pem"))
os.environ["IDENTITY_JWT_PRIVATE_KEY_PATH"] = str(_KEY_DIR / "private.pem")
os.environ["IDENTITY_JWT_PUBLIC_KEY_PATH"] = str(_KEY_DIR / "public.pem")
os.environ.setdefault("IDENTITY_JWKS_ISSUER", "https://auth.test.skyrict.io")
os.environ.setdefault("IDENTITY_JWKS_AUDIENCE", "api.test.skyrict.io")
os.environ.setdefault("IDENTITY_ENVIRONMENT", "test")
os.environ["IDENTITY_DEBUG"] = "false"
os.environ.setdefault(
    "IDENTITY_MFA_ENCRYPTION_KEY",
    Fernet.generate_key().decode("utf-8"),
)


@pytest.fixture(scope="session", autouse=True)
def _cleanup_ephemeral_keys():
    yield
    shutil.rmtree(_KEY_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def rsa_private_key() -> str:
    return (_KEY_DIR / "private.pem").read_text()


@pytest.fixture(scope="session")
def rsa_public_key() -> str:
    return (_KEY_DIR / "public.pem").read_text()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    try:
        from httpx import ASGITransport, AsyncClient

        from identity.api.lifespan import lifespan
        from identity.core.exceptions import StartupError
        from identity.main import app
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.skip(f"identity application unavailable: {exc}")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with (
            lifespan(app),
            AsyncClient(transport=transport, base_url="http://test") as http_client,
        ):
            yield http_client
    except StartupError as exc:
        pytest.skip(f"startup dependency verification failed: {exc}")
