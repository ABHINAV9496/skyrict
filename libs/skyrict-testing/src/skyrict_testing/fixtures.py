"""Shared pytest fixtures for Skyrict services.

Usage in service conftest.py:
    from skyrict_testing.fixtures import *
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# RSA key fixtures (for RS256 JWT testing)
# ---------------------------------------------------------------------------

# Look for RSA keys relative to the caller's working directory (project root),
# falling back to a location relative to this file for backward compat.
_FIXTURES_DIR = Path(__file__).parent


def _resolve_rsa_path(filename: str) -> Path | None:
    """Resolve an RSA key file path, checking project-relative then package-relative."""
    candidates = [
        Path.cwd() / "tests" / "fixtures" / "rsa" / filename,
        _FIXTURES_DIR / "fixtures" / "rsa" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


@pytest.fixture(scope="session")
def rsa_private_key() -> str:
    """Load the RSA private key from tests/fixtures/rsa/."""
    key_path = _resolve_rsa_path("private.pem")
    if key_path is None:
        pytest.skip("RSA test keys not found — generate with: python -m skyrict_testing.generate_keys")
    return key_path.read_text()


@pytest.fixture(scope="session")
def rsa_public_key() -> str:
    """Load the RSA public key from tests/fixtures/rsa/."""
    key_path = _resolve_rsa_path("public.pem")
    if key_path is None:
        pytest.skip("RSA test keys not found")
    return key_path.read_text()


# ---------------------------------------------------------------------------
# Backend fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def anyio_backend():
    """Use asyncio backend for pytest-asyncio."""
    return "asyncio"
