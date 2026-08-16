"""Shared fixtures for API integration tests (real Postgres required).

The TenantContextMiddleware resolves the tenant by slug with a database lookup
on every non-skipped request, so API integration tests need a reachable
Postgres (see tests/integration/conftest.py for ``migrated_schema``).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.core.tenant_context import TenantContext
from core.db.session import async_session_factory, engine
from core.models.tenant import TenantModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from httpx import AsyncClient

# "acme" is a reserved platform slug, so the canonical primary test tenant
# uses a non-reserved slug (mirrors identity's suite).
TENANT_ACME = "olympus"
TENANT_GLOBEX = "globex"
TENANT_DISABLED = "disabledco"

# Permission-test identities (HR-BE-002 Gap 1): the admin sub is granted the
# six ERP keys via core_user_roles; the "nobody" sub is deliberately ungranted
# so 403 tests never mutate a granted identity mid-suite.
ADMIN_ROLE = "organization_admin"


def _admin_sub(slug: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"skyrict:test:{slug}:admin"))


def _nobody_sub(slug: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"skyrict:test:{slug}:nobody"))


async def _upsert_test_user(tenant_id: uuid.UUID, sub: str) -> None:
    """Create the identity ``users`` row backing a deterministic test sub.

    The shared ``audit_logs`` table (identity-owned, migration 0001) enforces
    ``actor_user_id -> users(id) ON DELETE SET NULL``, so any audit write by a
    seeded test identity requires a real ``users`` row. Mirrors the raw insert
    used by the inventory suite's ``rbac_world`` fixture.
    """
    async with async_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, tenant_id, email, password_hash, full_name) "
                "VALUES (:id, :tenant_id, :email, :password_hash, :full_name) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": uuid.UUID(sub),
                "tenant_id": tenant_id,
                "email": f"{sub}@skyrict.integration.test",
                "password_hash": "not-a-real-hash",
                "full_name": sub[:8],
            },
        )
        await session.commit()


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
async def seeded_hr_defaults(integration_db: dict[str, str]) -> None:
    """Seed the olympus tenant's HR/Payroll defaults (leave types + settings).

    Idempotent — safe to re-run across tests sharing the tenant.
    """
    from core.seed import seed_tenant_hr_defaults

    await seed_tenant_hr_defaults(uuid.UUID(integration_db["acme_id"]))


@pytest.fixture(autouse=True)
async def seeded_test_rbac(integration_db: dict[str, str]) -> None:
    """Grant the deterministic test-admin identities the six ERP keys.

    Runs before every test: seeds the system roles for olympus and globex and
    links each tenant's admin sub to ``organization_admin`` (all six
    ``erp.hr.*`` / ``erp.payroll.*`` keys), and creates the identity ``users``
    rows backing every deterministic test sub so shared ``audit_logs`` writes
    (FK ``actor_user_id -> users(id)``) never violate the constraint.
    Idempotent — the grant uses ``ON CONFLICT DO NOTHING`` on the composite
    key. The "nobody" subs are intentionally NOT granted so 403 tests use a
    distinct ungranted identity instead of mutating a granted one mid-suite.
    """
    from core.models.core_role import CoreRoleModel
    from core.models.core_user_role import CoreUserRoleModel
    from core.seed import seed_core_roles_for_tenant

    for slug, key in ((TENANT_ACME, "acme_id"), (TENANT_GLOBEX, "globex_id")):
        tenant_id = uuid.UUID(integration_db[key])
        for sub in (_admin_sub(slug), _nobody_sub(slug)):
            await _upsert_test_user(tenant_id, sub)
        await seed_core_roles_for_tenant(tenant_id)
        async with async_session_factory() as session:
            role_id = await session.scalar(
                select(CoreRoleModel.id).where(
                    CoreRoleModel.tenant_id == tenant_id,
                    CoreRoleModel.name == ADMIN_ROLE,
                )
            )
            assert role_id is not None, "organization_admin role must be seeded"
            await session.execute(
                pg_insert(CoreUserRoleModel)
                .values(
                    tenant_id=tenant_id,
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(_admin_sub(slug)),
                    role_id=role_id,
                    scope_id=None,
                )
                .on_conflict_do_nothing()
            )
            await session.commit()


@pytest.fixture
def tenant_headers(
    integration_db: dict[str, str], rsa_private_key: str
) -> Callable[[str], dict[str, str]]:
    """Headers factory — signed JWT bound to a tenant's UUID + its slug header.

    Returns a stable admin identity (pre-granted all six ERP keys by
    ``seeded_test_rbac``). Pass ``unprivileged=True`` for a deliberately
    ungranted identity — the token is valid but resolves zero permissions, so
    permission-gated endpoints return 403 without disturbing the admin grant.
    """
    from .helpers import make_tenant_headers

    tenant_ids = {
        "olympus": integration_db["acme_id"],
        "globex": integration_db["globex_id"],
        "disabledco": integration_db["disabled_id"],
    }

    def _headers(slug: str = "olympus", *, unprivileged: bool = False) -> dict[str, str]:
        sub = _nobody_sub(slug) if unprivileged else _admin_sub(slug)
        return make_tenant_headers(rsa_private_key, tenant_ids[slug], slug, sub=sub)

    return _headers


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
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
