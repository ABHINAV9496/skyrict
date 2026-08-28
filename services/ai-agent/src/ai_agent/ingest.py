"""RAG ingestion runner — composition root for the ``ai-agent ingest`` CLI.

Wires the pieces the feature layer may not import itself (repositories,
sessions, settings) around the pure ingestion pipeline. Lives at the package
root so it can compose ``ai_agent.db`` + ``ai_agent.features`` without
violating the import-linter layering contracts.

RLS note: the session's ``after_begin`` hook sets
``app.current_tenant_id`` from ``TenantContext``; without it every write and
delete would silently match zero rows under the tenant policies. The runner
therefore pins the resolved tenant id BEFORE any statement runs.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

import structlog
import typer

from ai_agent.core.config import settings
from ai_agent.core.embedding import build_embedding_provider
from ai_agent.core.exceptions import StartupError
from ai_agent.core.tenant_context import TenantContext
from ai_agent.core.token_counter import TokenCounter
from ai_agent.db.rag_repository import RagRepository
from ai_agent.db.session import async_session_factory
from ai_agent.db.tenant_resolver import resolve_tenant_id
from ai_agent.features.rag.ingest.loader import (
    MODULE_ENDPOINTS,
    DocsLoader,
    ModuleLoader,
)
from ai_agent.features.rag.ingest.service import RagIngestService

if TYPE_CHECKING:
    from pathlib import Path

    from ai_agent.features.rag.ingest.loader import SourceDocument

logger = structlog.get_logger("ai_agent.rag.ingest")


async def run_ingest(
    *,
    source: str,
    module: str,
    tenant: str,
    path: Path | None,
    mode: str,
) -> None:
    """Ingest documents for one tenant; prints a structured summary."""
    if source not in {"docs", "module"}:
        raise typer.BadParameter("--source must be 'docs' or 'module'")
    if mode not in {"incremental", "full"}:
        raise typer.BadParameter("--mode must be 'incremental' or 'full'")

    provider = build_embedding_provider(settings)
    if provider is None:
        raise StartupError(
            "No embedding provider configured - set AI_EMBEDDING_PROVIDER=openai "
            "and AI_EMBEDDING_API_KEY"
        )

    if source == "module":
        if module not in MODULE_ENDPOINTS:
            raise StartupError(
                f"module loader has no configured endpoint for '{module}' "
                f"(known: {sorted(MODULE_ENDPOINTS)})"
            )
        if not settings.INGEST_TOKEN:
            raise StartupError(
                "AI_INGEST_TOKEN is required to pull module data from the core service"
            )

    async with async_session_factory() as session:
        tenant_id = await resolve_tenant_id(session, tenant)
        # Pin the security context BEFORE the first statement so the session's
        # RLS hook constrains every delete/insert to this tenant.
        TenantContext.set(str(tenant_id))
        TenantContext.set_tenant_slug(tenant if source == "module" else None)

        store = RagRepository(session)
        service = RagIngestService(
            counter=TokenCounter(),
            embedding_provider=provider,
            store=store,
            child_tokens=settings.RAG_CHUNK_CHILD_TOKENS,
            parent_tokens=settings.RAG_CHUNK_PARENT_TOKENS,
            overlap_tokens=settings.RAG_CHUNK_OVERLAP_TOKENS,
        )

        documents = await _load_documents(source=source, module=module, path=path, tenant=tenant)
        if not documents:
            typer.echo("No documents to ingest.")
            return

        report = await service.ingest(tenant_id=tenant_id, documents=documents)
        await session.commit()

    typer.echo(
        f"Ingested {report.docs_processed} document(s) for tenant {tenant} "
        f"({report.parents} parents / {report.children} children, "
        f"{report.tokens_embedded} tokens, model={report.model_used} dims={report.dims}, "
        f"latency={report.total_latency_ms}ms, skipped={report.docs_skipped_empty})"
    )
    logger.info(
        "rag.ingest_complete",
        tenant_id=str(tenant_id),
        source=source,
        module=module,
        mode=mode,
        **asdict(report),
    )


async def _load_documents(
    *,
    source: str,
    module: str,
    path: Path | None,
    tenant: str,
) -> list[SourceDocument]:
    """Load source documents through the configured loader."""
    if source == "docs":
        if path is None:
            raise StartupError("--path is required when --source=docs")
        return DocsLoader(root=path).load()
    loader = ModuleLoader(
        base_url=settings.INVENTORY_SERVICE_URL,
        bearer_token=settings.INGEST_TOKEN,
        tenant_slug=tenant,
        timeout_seconds=settings.INVENTORY_SERVICE_TIMEOUT_SECONDS,
    )
    return await loader.load(module)
