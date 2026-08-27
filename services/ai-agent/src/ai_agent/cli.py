"""Typer CLI for the AI agent service."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import typer

# services/ai-agent - the alembic.ini lives here; the CLI is invoked via
# `uv run --directory services/ai-agent ai-agent ...`, so never resolve
# relative to the process CWD (which is already services/ai-agent, making a
# nested path). cli.py lives at services/ai-agent/src/ai_agent/, so
# parents[2] is services/ai-agent.
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]

app = typer.Typer(name="ai-agent", help="Skyrict AI agent service CLI", no_args_is_help=True)


@app.command()
def serve(
    port: int = typer.Option(8002, help="Port to bind."),
    reload: bool = typer.Option(False, help="Enable auto-reload (dev only)."),
) -> None:
    """Run the AI agent service with uvicorn."""
    import uvicorn

    uvicorn.run(
        "ai_agent.main:app",
        host="0.0.0.0",  # dev server bind; containers bind anyway
        port=port,
        reload=reload,
    )


@app.command()
def migrate(head: str = typer.Option("head", help="Alembic target revision")) -> None:
    """Run database migrations (version table: alembic_version_ai)."""
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", head],
        cwd=_PACKAGE_ROOT,
        check=True,
    )


@app.command()
def digest(
    tenant_id: str = typer.Option(..., help="Target tenant UUID"),
    tenant_slug: str = typer.Option(..., help="Target tenant slug"),
) -> None:
    """Produce and print today's cross-module narrated digest for one tenant."""

    async def _run() -> None:
        from datetime import UTC, datetime

        from ai_agent.core.audit_service import AuditService
        from ai_agent.core.config import settings
        from ai_agent.core.llm_router import LlmRouter
        from ai_agent.core.providers import build_providers_from_settings
        from ai_agent.db.audit_repository import AiAuditLogRepository
        from ai_agent.db.digest_repository import DigestCacheRepository
        from ai_agent.db.session import async_session_factory
        from ai_agent.features.narrator.gateway import HttpCoreGateway
        from ai_agent.features.narrator.service import NarratorService

        llm_router = LlmRouter(build_providers_from_settings(settings))
        async with async_session_factory() as session:
            service = NarratorService(
                gateway=HttpCoreGateway(
                    base_url=str(settings.INVENTORY_SERVICE_URL),
                    bearer_token="",
                    tenant_slug=tenant_slug,
                ),
                llm_router=llm_router,
                cache=DigestCacheRepository(session),
                audit=AuditService(AiAuditLogRepository(session)),
                allow_llm=settings.NARRATOR_ALLOW_LLM,
                allow_refresh=True,
            )
            result = await service.digest(
                tenant_id=uuid.UUID(tenant_id),
                user_id=None,
                as_of=datetime.now(tz=UTC).date(),
                force_refresh=True,
            )
            await session.commit()
        typer.echo(f"status={result.status} source={result.source}")
        if result.title:
            typer.echo(result.title)
        if result.summary:
            typer.echo(result.summary)
        for point in result.points:
            typer.echo(f"- {point}")
        if result.caveat:
            typer.echo(result.caveat)

    asyncio.run(_run())


if __name__ == "__main__":
    app()
