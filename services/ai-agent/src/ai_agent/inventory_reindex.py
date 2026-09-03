"""Inventory snapshot reindex runner - composition root for the ``inventory
reindex`` CLI.

Wires the pieces the feature layer may not import itself (repositories,
sessions, settings) around the pure snapshot pipeline, mirroring
``ai_agent/ingest.py``. Lives at the package root so it can compose
``ai_agent.db`` + ``ai_agent.features`` without violating the import-linter
layering contracts.

RLS note: the session's ``after_begin`` hook sets ``app.current_tenant_id``
from ``TenantContext``; without it every write and delete would silently match
zero rows under the tenant policies. The runner therefore pins the resolved
tenant id BEFORE any statement runs.
"""

from __future__ import annotations

import typer

from ai_agent.core.config import settings
from ai_agent.core.embedding import build_embedding_provider
from ai_agent.core.exceptions import StartupError
from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.inventory_embedding_repository import InventoryEmbeddingRepository
from ai_agent.db.session import async_session_factory
from ai_agent.db.tenant_resolver import resolve_tenant_id
from ai_agent.features.inventory_semantic.loader import ProductSnapshotLoader
from ai_agent.features.inventory_semantic.snapshot import InventorySnapshotSyncService


async def run_inventory_reindex(*, tenant: str, mode: str) -> None:
    """Rebuild one tenant's product embedding snapshot; prints a summary."""
    if mode not in {"incremental", "full"}:
        raise typer.BadParameter("--mode must be 'incremental' or 'full'")

    provider = build_embedding_provider(settings)
    if provider is None:
        raise StartupError(
            "No embedding provider configured - set AI_EMBEDDING_PROVIDER=openai "
            "and AI_EMBEDDING_API_KEY"
        )
    if not settings.INGEST_TOKEN:
        raise StartupError(
            "AI_INGEST_TOKEN is required to pull the product catalog from the core service"
        )

    async with async_session_factory() as session:
        tenant_id = await resolve_tenant_id(session, tenant)
        # Pin the security context BEFORE the first statement so the session's
        # RLS hook constrains every delete/insert to this tenant.
        TenantContext.set(str(tenant_id))
        TenantContext.set_tenant_slug(tenant)

        repository = InventoryEmbeddingRepository(session)
        service = InventorySnapshotSyncService(
            embedding_provider=provider,
            store=repository,
        )
        if mode == "full":
            await repository.delete_all(tenant_id=tenant_id)

        loader = ProductSnapshotLoader(
            base_url=settings.INVENTORY_SERVICE_URL,
            bearer_token=settings.INGEST_TOKEN,
            tenant_slug=tenant,
            timeout_seconds=settings.INVENTORY_SERVICE_TIMEOUT_SECONDS,
        )
        products = await loader.load_all()
        if not products:
            typer.echo(f"No products to index for tenant {tenant}.")
            return

        report = await service.apply(tenant_id=tenant_id, upserts=products, removes=[])
        await session.commit()

    typer.echo(
        f"Reindexed tenant {tenant} ({mode}): {report.upserts_applied} product(s) "
        f"embedded, model={report.model_used} dims={report.dims}"
    )
