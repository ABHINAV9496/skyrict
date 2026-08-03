"""Shared fixtures for API integration tests (real Postgres required).

The TenantContextMiddleware resolves the tenant by slug with a database lookup
on every non-skipped request, so API integration tests need a reachable
Postgres. When it is unavailable (local dev without Docker), the whole API
integration suite is skipped — CI runs it against a provisioned database.

The session-scoped ``migrated_schema`` fixture applies ``alembic upgrade head``
once (real migrations — RLS policies, audit triggers, permission catalog — not
``create_all``). The autouse ``integration_db`` fixture then seeds the
isolation fixtures (tenants acme/globex/disabledco + user alice@acme.io) and
removes only the rows it created.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from asyncpg.exceptions import PostgresError
from sqlalchemy import delete, select, text

# Import the model registry so SQLAlchemy can configure cross-module
# relationships (same set the app and alembic use).
from identity.core.tenant_context import TenantContext
from identity.db.models import (  # noqa: F401  # register every ORM model
    AuditLogModel,
    PermissionModel,
    RoleModel,
    SessionModel,
    TenantModel,
    UserModel,
    UserRoleModel,
)
from identity.db.session import async_session_factory, engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

TENANT_ACME = "acme"
TENANT_GLOBEX = "globex"
TENANT_DISABLED = "disabledco"
USER_A_EMAIL = "alice@acme.io"

_ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"


@pytest.fixture(scope="session")
async def migrated_schema() -> None:
    """Apply ``alembic upgrade head`` once; skip when Postgres is unreachable.

    Runs alembic in a subprocess (fresh interpreter) so it can call
    ``asyncio.run()`` without colliding with the pytest-asyncio event loop.
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
    except (OSError, PostgresError) as exc:
        pytest.skip(f"database unavailable: {exc}")

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(_ALEMBIC_INI), "upgrade", "head"],
        cwd=_ALEMBIC_INI.parent,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"alembic upgrade failed: {result.stderr.strip() or result.stdout.strip()}")

    # This fixture is session-scoped, so its engine connection lives on the
    # pytest-asyncio *session* event loop. Drop it now: function-scoped tests
    # run on their own loops, and a pooled connection must never cross loops.
    await engine.dispose()


@pytest.fixture(autouse=True)
async def integration_db(migrated_schema: None) -> AsyncGenerator[dict[str, str], None]:
    """Seed isolation fixtures after the schema exists; clean up only its rows."""
    # Fresh context — no tenant can leak from a previous test into this one.
    TenantContext.reset()

    created_tenant_slugs: list[str] = []
    user_created = False

    async with async_session_factory() as session:
        tenant_specs = [
            (TENANT_ACME, "Acme Corp", True),
            (TENANT_GLOBEX, "Globex Inc", True),
            (TENANT_DISABLED, "Shuttered Co", False),
        ]
        ids: dict[str, str] = {}
        for slug, name, is_active in tenant_specs:
            existing_id = await session.scalar(
                select(TenantModel.id).where(TenantModel.slug == slug)
            )
            if existing_id is not None:
                ids[slug] = str(existing_id)
            else:
                row = TenantModel(
                    id=uuid.uuid4(), name=name, slug=slug, is_active=is_active, plan_tier="free"
                )
                session.add(row)
                await session.flush()
                ids[slug] = str(row.id)
                created_tenant_slugs.append(slug)

        user_id = await session.scalar(select(UserModel.id).where(UserModel.email == USER_A_EMAIL))
        if user_id is None:
            row = UserModel(
                id=uuid.uuid4(),
                tenant_id=ids[TENANT_ACME],
                email=USER_A_EMAIL,
                password_hash="integration-test-hash",
                full_name="Alice Acme",
                is_active=True,
                is_verified=True,
            )
            session.add(row)
            await session.flush()
            user_id = row.id
            user_created = True
        await session.commit()

        yield {
            "acme_id": ids[TENANT_ACME],
            "globex_id": ids[TENANT_GLOBEX],
            "disabled_id": ids[TENANT_DISABLED],
            "user_a_id": str(user_id),
        }

    # Cleanup — only rows this fixture created.
    async with async_session_factory() as session:
        if created_tenant_slugs:
            await session.execute(
                delete(TenantModel).where(TenantModel.slug.in_(created_tenant_slugs))
            )
        if user_created:
            await session.execute(delete(UserModel).where(UserModel.id == user_id))
        await session.commit()

    # pytest-asyncio gives every test its own event loop; drop pooled
    # connections (created on this test's loop) so the next test cannot reuse
    # a connection bound to a closed loop.
    await engine.dispose()
