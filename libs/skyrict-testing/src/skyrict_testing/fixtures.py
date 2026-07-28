"""Shared pytest fixtures for Skyrict services.

Usage in service conftest.py:
    from skyrict_testing.fixtures import *
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncGenerator

import pytest

# ---------------------------------------------------------------------------
# RSA key fixtures (for RS256 JWT testing)
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent


@pytest.fixture(scope="session")
def rsa_private_key() -> str:
    """Load the RSA private key from tests/fixtures/rsa/."""
    key_path = _FIXTURES_DIR / "fixtures" / "rsa" / "private.pem"
    if not key_path.exists():
        pytest.skip("RSA test keys not found — generate with: python -m skyrict_testing.generate_keys")
    return key_path.read_text()


@pytest.fixture(scope="session")
def rsa_public_key() -> str:
    """Load the RSA public key from tests/fixtures/rsa/."""
    key_path = _FIXTURES_DIR / "fixtures" / "rsa" / "public.pem"
    if not key_path.exists():
        pytest.skip("RSA test keys not found")
    return key_path.read_text()


# ---------------------------------------------------------------------------
# HTTP client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def anyio_backend():
    """Use asyncio backend for pytest-asyncio."""
    return "asyncio"
