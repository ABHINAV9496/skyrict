"""Shared integration fixtures — real Postgres required (skipped when unavailable).

The session-scoped ``migrated_schema`` fixture applies the identity migration
chain FIRST (core's 0001 FKs ``tenant_id -> tenants(id)`` and the shared
``current_tenant_id()`` function, so identity's base schema must exist), then
core's own chain under its ``alembic_version_core`` version table — real
migrations against real Postgres, not ``create_all``.

Event-loop discipline: pytest-asyncio gives every function-scoped async test
its own event loop, but the SQLAlchemy engine is a process-wide singleton with
a connection pool. Any pooled connection is bound to the loop that created it,
so a connection created on one loop and reused on another dies with
"Future attached to a different loop". The rule for every fixture wider than
function scope is therefore: do all DB work inside a single ``asyncio.run()``
and ``await engine.dispose()`` BEFORE that run's loop closes — the pool is
empty when tests on their own loops start.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from asyncpg.exceptions import PostgresError
from cryptography.fernet import Fernet
from sqlalchemy import text

from core.db.session import engine

_ROOT = Path(__file__).resolve().parents[2]  # services/core
_CORE_ALEMBIC_INI = _ROOT / "alembic.ini"
_IDENTITY_ALEMBIC_INI = _ROOT.parent / "identity" / "alembic.ini"


def _configure_identity_env() -> None:
    """Export IDENTITY_* env vars so identity's alembic subprocess can boot.

    Core shares the identity database; the identity migration chain must run
    first (it creates ``tenants`` and ``public.current_tenant_id()``). Identity
    Settings fails fast on missing IDENTITY_* vars, so mirror the conftest
    defaults here (keys from the same ephemeral temp dir).
    """
    public_key_path = os.environ.get("CORE_JWT_PUBLIC_KEY_PATH", "")
    private_key_path = public_key_path.replace("public.pem", "private.pem")
    os.environ.setdefault("IDENTITY_DATABASE_URL", os.environ["CORE_DATABASE_URL"])
    os.environ.setdefault("IDENTITY_REDIS_URL", "redis://localhost:6379/0")
    os.environ.setdefault("IDENTITY_ENVIRONMENT", "test")
    os.environ.setdefault("IDENTITY_JWT_PRIVATE_KEY_PATH", private_key_path)
    os.environ.setdefault("IDENTITY_JWT_PUBLIC_KEY_PATH", public_key_path)
    os.environ.setdefault("IDENTITY_JWKS_ISSUER", "https://auth.test.skyrict.io")
    os.environ.setdefault("IDENTITY_JWKS_AUDIENCE", "api.test.skyrict.io")
    os.environ.setdefault(
        "IDENTITY_MFA_ENCRYPTION_KEY",
        Fernet.generate_key().decode("utf-8"),
    )


_configure_identity_env()


@pytest.fixture(autouse=True)
async def _dispose_db_pool_after_each_test():
    """Drop pooled connections after every test.

    pytest-asyncio gives each function-scoped async test its own event loop,
    but the SQLAlchemy engine is a process-wide singleton: a connection
    created on one test's loop and returned to the pool is reused by the next
    test's loop and dies with "Event loop is closed". Disposing after every
    test keeps the pool empty at the start of each test's loop. Idempotent.
    """
    yield
    await engine.dispose()


async def _probe_database() -> None:
    """Round-trip against Postgres; dispose the pool before the loop closes."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def migrated_schema() -> None:
    """Run identity then core ``alembic upgrade head`` once; skip if no Postgres.

    A plain (sync) fixture: each migration runs in a fresh interpreter
    subprocess so its env.py can ``asyncio.run()`` without colliding with
    pytest-asyncio's loop management.
    """
    try:
        asyncio.run(_probe_database())
    except (OSError, PostgresError) as exc:
        pytest.skip(f"database unavailable: {exc}")

    for ini, cwd in (
        (_IDENTITY_ALEMBIC_INI, _IDENTITY_ALEMBIC_INI.parent),
        (_CORE_ALEMBIC_INI, _CORE_ALEMBIC_INI.parent),
    ):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(ini), "upgrade", "head"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(
                f"alembic upgrade failed ({ini.name}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
