"""Shared fixtures for API integration tests (real Postgres required).

The TenantContextMiddleware resolves the tenant by slug with a database lookup
on every non-skipped request, so API integration tests need a reachable
Postgres (see tests/integration/conftest.py for ``migrated_schema``).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete, select

from core.core.tenant_context import TenantContext
from core.db.session import async_session_factory, engine
from core.models.tenant import TenantModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# "acme" is a reserved platform slug, so the canonical primary test tenant
# uses a non-reserved slug (mirrors identity's suite).
TENANT_ACME = "olympus"
TENANT_GLOBEX = "globex"
TENANT_DISABLED = "disabledco"


@pytest.fixture(autouse=True)
async def integration_db(migrated_schema: None) -> AsyncGenerator[dict[str, str], None]:
    """Seed isolation fixtures after the schema exists; clean up only its rows."""
    TenantContext.reset()

    created_tenant_slugs: list[str] = []

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
        await session.commit()

        yield {
            "acme_id": ids[TENANT_ACME],
            "globex_id": ids[TENANT_GLOBEX],
            "disabled_id": ids[TENANT_DISABLED],
        }

    async with async_session_factory() as session:
        if created_tenant_slugs:
            await session.execute(
                delete(TenantModel).where(TenantModel.slug.in_(created_tenant_slugs))
            )
        await session.commit()

    # pytest-asyncio gives every test its own event loop; drop pooled
    # connections (created on this test's loop) so the next test cannot reuse
    # a connection bound to a closed loop. This also clears any session-level
    # SET ROLE left by the RLS smoke test.
    await engine.dispose()


@pytest.fixture
async def client():
    """Async HTTP client against the FastAPI app (ASGI transport).

    Runs the REAL application lifespan (startup dependency verification +
    graceful shutdown) so integration tests exercise the lifecycle. Skips the
    test when startup verification fails (database unreachable).
    """
    try:
        from httpx import ASGITransport, AsyncClient

        from core.api.lifespan import lifespan
        from core.core.exceptions import StartupError
        from core.main import app
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.skip(f"core application unavailable: {exc}")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with (
            lifespan(app),
            AsyncClient(transport=transport, base_url="http://test") as http_client,
        ):
            yield http_client
    except StartupError as exc:
        pytest.skip(f"startup dependency verification failed: {exc}")
