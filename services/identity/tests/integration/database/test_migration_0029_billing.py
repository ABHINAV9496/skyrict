"""0029+0030 billing migrations up/down round-trip on a scratch database (SKY-33).

Proves the billing migrations in isolation against a disposable database:
upgrade the identity chain to 0027, seed a tenant row carrying the legacy
``professional`` tier value, upgrade to head (runs 0028 erp permissions,
0029 billing, then 0030 webhook lifecycle: ``grace_started_at`` +
``processed_stripe_events``), assert the new billing columns exist, the row
was canonicalized to ``pro`` and the CHECK constraint rejects the old literal
- then downgrade back to 0027 and assert the reverse (columns gone, row
reverted to ``professional``).

The test owns its scratch database and never touches the shared test
database (``migrated_schema``): it destroys the schema it builds.
``asyncio.run()`` wraps each DB phase and disposes every engine before the
loop closes (the fixture discipline from tests/integration/api/conftest.py).
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_IDENTITY_DIR = Path(__file__).resolve().parents[3]  # services/identity
_ALEMBIC_INI = _IDENTITY_DIR / "alembic.ini"

# Columns introduced across 0029 (billing) and 0030 (grace period) - both must
# be present at head and both must be gone again after the 0027 downgrade.
_BILLING_COLUMNS = (
    "trial_ends_at",
    "subscription_status",
    "stripe_customer_id",
    "stripe_subscription_id",
    "billing_email",
    "grace_started_at",
)


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
    """Run alembic in a fresh interpreter with env overrides (mirrors migrated_schema).

    cwd is the identity service directory so pydantic-settings picks up the
    local ``.env`` (critical vars like the JWT key paths) while the
    IDENTITY_DATABASE_URL override redirects alembic at the scratch database.
    """
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


async def _seed_legacy_professional(url: str) -> str:
    """Insert a tenant with the pre-0029 ``professional`` tier after upgrade 0027."""
    engine = create_async_engine(url, poolclass=NullPool)
    tenant_id = str(uuid.uuid4())
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, plan_tier, is_active) "
                    "VALUES (:id, :name, :slug, 'professional', true)"
                ),
                {
                    "id": uuid.UUID(tenant_id),
                    "name": "Legacy Pro Tenant",
                    "slug": f"legacy-pro-{tenant_id[:8]}",
                },
            )
            await conn.commit()
        return tenant_id
    finally:
        await engine.dispose()


async def _assert_upgraded(url: str, tenant_id: str) -> None:
    """Post-0029 assertions: columns exist, CHECK accepts 'pro', row canonicalized."""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            version = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert version == "0030", f"head is {version}, expected 0030"

            cols = {
                row[0]
                for row in await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'tenants'"
                    )
                )
            }
            assert set(_BILLING_COLUMNS) <= cols, (
                f"0029 missing columns: {set(_BILLING_COLUMNS) - cols}"
            )

            status_col = (
                await conn.execute(
                    text(
                        "SELECT column_default, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'public' "
                        "AND table_name = 'tenants' "
                        "AND column_name = 'subscription_status'"
                    )
                )
            ).one()
            assert status_col[0] is not None and "none" in status_col[0], status_col
            assert status_col[1] == "NO", status_col

            check_def = (
                await conn.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conrelid = 'public.tenants'::regclass "
                        "AND conname = 'ck_tenants_plan_tier'"
                    )
                )
            ).scalar_one()
            assert "'pro'" in check_def, f"0029 CHECK must allow 'pro': {check_def}"
            assert "professional" not in check_def, (
                f"0029 CHECK must drop 'professional': {check_def}"
            )

            tier = (
                await conn.execute(
                    text("SELECT plan_tier FROM tenants WHERE id = :id"),
                    {"id": uuid.UUID(tenant_id)},
                )
            ).scalar_one()
            assert tier == "pro", f"0029 must canonicalize professional→pro, got {tier!r}"

            rejected = False
            try:
                await conn.execute(
                    text(
                        "INSERT INTO tenants (id, name, slug, plan_tier, is_active) "
                        "VALUES (:id, :name, :slug, 'professional', true)"
                    ),
                    {
                        "id": uuid.UUID(str(uuid.uuid4())),
                        "name": "Should Fail",
                        "slug": f"should-fail-{uuid.uuid4().hex[:8]}",
                    },
                )
                await conn.commit()
            except IntegrityError:
                rejected = True
                await conn.rollback()
            assert rejected, "0029 CHECK must reject the legacy 'professional' tier"

            unique_customer = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM pg_indexes "
                        "WHERE schemaname = 'public' "
                        "AND tablename = 'tenants' "
                        "AND indexdef LIKE '%stripe_customer_id%'"
                    )
                )
            ).scalar_one()
            assert unique_customer >= 1, (
                "0029 must add a uniqueness constraint on stripe_customer_id"
            )
    finally:
        await engine.dispose()


async def _assert_downgraded(url: str, tenant_id: str) -> None:
    """Post-downgrade assertions: columns gone, CHECK reverted, row reverted."""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            version = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert version == "0027", f"downgrade landed on {version}, expected 0027"

            cols = {
                row[0]
                for row in await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'tenants'"
                    )
                )
            }
            assert not set(_BILLING_COLUMNS) & cols, (
                f"downgrade left billing columns: {set(_BILLING_COLUMNS) & cols}"
            )

            check_def = (
                await conn.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conrelid = 'public.tenants'::regclass "
                        "AND conname = 'ck_tenants_plan_tier'"
                    )
                )
            ).scalar_one()
            assert "'professional'" in check_def, (
                f"downgrade CHECK must restore 'professional': {check_def}"
            )

            tier = (
                await conn.execute(
                    text("SELECT plan_tier FROM tenants WHERE id = :id"),
                    {"id": uuid.UUID(tenant_id)},
                )
            ).scalar_one()
            assert tier == "professional", f"downgrade must revert pro→professional, got {tier!r}"
    finally:
        await engine.dispose()


def test_0029_billing_roundtrip() -> None:
    """billing columns + plan_tier canonicalization survive a full up/down."""
    from identity.core.config import settings

    dbname = f"skyrict_billing_rt_{uuid.uuid4().hex[:8]}"
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

        _run_alembic(
            _ALEMBIC_INI,
            ["upgrade", "0027"],
            overrides,
        )

        tenant_id = asyncio.run(_seed_legacy_professional(scratch_url))

        _run_alembic(_ALEMBIC_INI, ["upgrade", "head"], overrides)
        asyncio.run(_assert_upgraded(scratch_url, tenant_id))

        _run_alembic(_ALEMBIC_INI, ["downgrade", "0027"], overrides)
        asyncio.run(_assert_downgraded(scratch_url, tenant_id))
    finally:
        asyncio.run(_drop_scratch_db(maint_dsn, dbname))
