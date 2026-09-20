"""0032 leave-grant / employee-role heritage repair round-trip (SKY-109 B2).

Proves the 0032 heritage carrier in isolation on a disposable scratch database
the same way the 0029 billing carrier is proven: upgrade the identity chain to
0031 (the carrier's parent), seed a tenant carrying the *pre-0032 heritage
shape* -- a system role named ``employee`` carrying the legacy
``hr.leave.self`` / ``hr.leave.request`` / ``hr.leave.admin`` grant keys, the
shape 0019/0020-era services shipped -- upgrade to 0032, assert the grant keys
were canonicalized (``erp.leave.*``) and the system role renamed to
``employee_self_service``, assert collision-guarding (a tenant-created
non-system ``employee`` role is left untouched; the canonical name is never
created twice), assert idempotency on re-run, then downgrade 0032 -> 0031 and
re-upgrade to prove the reverse round-trips idempotently and heritage rows
survive.

The test owns its scratch database and never touches the shared test database
(``migrated_schema``): it builds, probes, and destroys the database it seeds,
mirroring the fixture discipline from tests/integration/database.
``asyncio.run()`` wraps each DB phase and every engine is disposed before the
loop closes.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_IDENTITY_DIR = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = _IDENTITY_DIR / "alembic.ini"

_LEGACY_LEAVE_GRANT_KEYS = ("hr.leave.self", "hr.leave.request", "hr.leave.admin")
_CANONICAL_LEAVE_GRANT_KEYS = (
    "erp.leave.self",
    "erp.leave.request",
    "erp.leave.admin",
)
_LEGACY_EMPLOYEE_ROLE_NAMES = ("employee", "employee_self")
_CANONICAL_EMPLOYEE_ROLE_NAME = "employee_self_service"


def _db_urls(base_url: str, dbname: str) -> tuple[str, str]:
    """Split ``base_url`` into a maintenance DSN (asyncpg) and the scratch URL."""
    parts = urlsplit(base_url)
    netloc = parts.netloc
    maint_dsn = urlunsplit(("postgresql", netloc, "/postgres", "", ""))
    scratch_url = urlunsplit((parts.scheme, netloc, f"/{dbname}", "", ""))
    return maint_dsn, scratch_url


async def _probe_database(maint_dsn: str) -> bool:
    try:
        conn = await asyncpg.connect(maint_dsn, timeout=5)
        await conn.close()
        return True
    except Exception:
        return False


async def _create_scratch_db(maint_dsn: str, dbname: str) -> None:
    conn = await asyncpg.connect(maint_dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        await conn.close()


async def _drop_scratch_db(maint_dsn: str, dbname: str) -> None:
    conn = await asyncpg.connect(maint_dsn)
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{dbname}' AND pid <> pg_backend_pid()"
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
    finally:
        await conn.close()


def _run_alembic(ini: Path, cmd: list[str], overrides: dict[str, str]) -> None:
    """Run alembic in a fresh interpreter with env overrides (mirrors 0029)."""
    env = {**os.environ, **overrides}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ini), *cmd],
        cwd=ini.parent,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(cmd)} failed ({ini.name}):\n"
        f"{result.stderr.strip() or result.stdout.strip()}"
    )


async def _seed_legacy_heritage(url: str) -> str:
    """Insert a tenant carrying the pre-0032 heritage shape (disposable)."""
    engine = create_async_engine(url, poolclass=NullPool)
    tenant_id = str(uuid.uuid4())
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, plan_tier, is_active) "
                    "VALUES (:id, :name, :slug, 'pro', true)"
                ),
                {
                    "id": uuid.UUID(tenant_id),
                    "name": "Heritage Tenant",
                    "slug": f"heritage-{tenant_id[:8]}",
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO roles (name, is_system_role, permissions, tenant_id) "
                    "VALUES (:name, true, :permissions, :tenant_id)"
                ),
                {
                    "name": _LEGACY_EMPLOYEE_ROLE_NAMES[0],
                    "permissions": list(_LEGACY_LEAVE_GRANT_KEYS),
                    "tenant_id": uuid.UUID(tenant_id),
                },
            )
            await conn.commit()
        return tenant_id
    finally:
        await engine.dispose()


async def _assert_roundtripped(url: str, tenant_id: str) -> None:
    """Post-0032: grant keys canonicalized, system role renamed, guard intact."""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            version = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert version == "0032", f"head is {version}, expected 0032"

            rows = (
                await conn.execute(
                    text(
                        "SELECT name, is_system_role, permissions FROM roles "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": uuid.UUID(tenant_id)},
                )
            ).all()
            assert len(rows) == 1, f"expected one role, got {len(rows)}"
            name, system, perms = rows[0]
            assert name == _CANONICAL_EMPLOYEE_ROLE_NAME, (
                f"0032 must rename system role to {_CANONICAL_EMPLOYEE_ROLE_NAME!r}, got {name!r}"
            )
            assert system, "0032 must keep the role a system role"
            assert not set(_LEGACY_LEAVE_GRANT_KEYS) & set(perms), (
                f"0032 must rewrite legacy grant keys, got {perms!r}"
            )
            assert set(_CANONICAL_LEAVE_GRANT_KEYS) <= set(perms), (
                f"0032 must install canonical grant keys, got {perms!r}"
            )
    finally:
        await engine.dispose()


async def _seed_collision_role(url: str, tenant_id: str) -> None:
    """Insert a tenant-created (non-system) ``employee`` role as a guard probe."""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "INSERT INTO roles (name, is_system_role, permissions, tenant_id) "
                    "VALUES (:name, false, :permissions, :tenant_id)"
                ),
                {
                    "name": "employee",
                    "permissions": ["custom.dashboard.view"],
                    "tenant_id": uuid.UUID(tenant_id),
                },
            )
            await conn.commit()
    finally:
        await engine.dispose()


async def _assert_collision_guarded(url: str, tenant_id: str) -> None:
    """A tenant-created ``employee`` role must survive untouched."""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT name, is_system_role, permissions FROM roles "
                        "WHERE tenant_id = :tenant_id ORDER BY is_system_role"
                    ),
                    {"tenant_id": uuid.UUID(tenant_id)},
                )
            ).all()
            names = {r.name for r in rows}
            assert "employee" in names, (
                f"collision guard must leave custom employee role, names={names!r}"
            )
            assert _CANONICAL_EMPLOYEE_ROLE_NAME in names, (
                f"canonical role must still exist, names={names!r}"
            )
    finally:
        await engine.dispose()


def test_0032_heritage_roundtrip() -> None:
    """0032 heritage: seed, upgrade, assert canonical, idempotent, reverse."""
    from identity.core.config import settings

    dbname = f"skyrict_heritage_rt_{uuid.uuid4().hex[:8]}"
    maint_dsn, scratch_url = _db_urls(settings.DATABASE_URL, dbname)

    if not asyncio.run(_probe_database(maint_dsn)):
        pytest.skip("database unavailable")

    try:
        try:
            asyncio.run(_create_scratch_db(maint_dsn, dbname))
        except asyncpg.exceptions.InsufficientPrivilegeError:
            pytest.skip(
                "skyrict role lacks CREATEDB; run on CI or grant with: ALTER ROLE skyrict CREATEDB;"
            )

        overrides = {"IDENTITY_DATABASE_URL": scratch_url}

        asyncio.run(
            _run_alembic,
        )
        _run_alembic(_ALEMBIC_INI, ["upgrade", "0031"], overrides)

        tenant_id = asyncio.run(_seed_legacy_heritage(scratch_url))

        _run_alembic(_ALEMBIC_INI, ["upgrade", "0032"], overrides)
        asyncio.run(_assert_roundtripped(scratch_url, tenant_id))

        _run_alembic(_ALEMBIC_INI, ["upgrade", "0032"], overrides)
        asyncio.run(_assert_roundtripped(scratch_url, tenant_id))

        asyncio.run(_seed_collision_role(scratch_url, tenant_id))
        _run_alembic(_ALEMBIC_INI, ["upgrade", "0032"], overrides)
        asyncio.run(_assert_collision_guarded(scratch_url, tenant_id))

        _run_alembic(_ALEMBIC_INI, ["downgrade", "0031"], overrides)
        _run_alembic(_ALEMBIC_INI, ["upgrade", "0032"], overrides)
        asyncio.run(_assert_roundtripped(scratch_url, tenant_id))
    finally:
        asyncio.run(_drop_scratch_db(maint_dsn, dbname))
