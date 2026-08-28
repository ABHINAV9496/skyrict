"""Typer CLI for the AI agent service."""

from __future__ import annotations

import sys
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
def ingest(
    source: str = typer.Option(
        "docs", help="source: 'docs' (markdown dir) or 'module' (core data)"
    ),
    module: str = typer.Option("docs", help="module name ('docs' or e.g. 'products')"),
    tenant: str = typer.Option(..., help="tenant slug (required)"),
    path: Path | None = None,
    mode: str = typer.Option(
        "incremental", help="'incremental' or 'full' (both replace idempotently)"
    ),
) -> None:
    """Ingest documents into the RAG vector store (SKY-58).

    --path: markdown directory root when --source=docs. Re-running a document
    is always safe (both modes replace idempotently).

    Requires an embedding provider: AI_EMBEDDING_PROVIDER + AI_EMBEDDING_API_KEY.
    """
    import asyncio

    from ai_agent.ingest import run_ingest

    asyncio.run(run_ingest(source=source, module=module, tenant=tenant, path=path, mode=mode))


if __name__ == "__main__":
    app()
