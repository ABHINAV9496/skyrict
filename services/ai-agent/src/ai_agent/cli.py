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


@app.command(name="eval")
def evaluate(
    tenant: str = typer.Option(..., help="tenant slug or UUID (required)"),
    module: str | None = typer.Option(
        None, help="restrict eval cases to one module ('docs' or 'products')"
    ),
    faithfulness: float = typer.Option(0.80, min=0.0, max=1.0, help="minimum faithfulness"),
    answer_relevancy: float = typer.Option(0.75, min=0.0, max=1.0, help="minimum answer relevancy"),
    context_precision: float = typer.Option(
        0.70, min=0.0, max=1.0, help="minimum context precision"
    ),
    context_recall: float = typer.Option(0.70, min=0.0, max=1.0, help="minimum context recall"),
) -> None:
    """Run the nightly RAGAS retrieval-quality gate (SKY-58).

    Runs every curated eval case through the REAL retrieval pipeline, scores
    the pairs with RAGAS, persists the run to ai_eval_runs, and exits nonzero
    when any metric drops below its threshold (CI gate).

    Requires ragas (nightly workflow installs it ephemerally):
    uv run --with "ragas>=0.2,<0.3" ai-agent eval --tenant <slug|uuid>
    """
    import asyncio

    from ai_agent.rag_eval import run_eval

    thresholds = {
        "faithfulness": faithfulness,
        "answer_relevancy": answer_relevancy,
        "context_precision": context_precision,
        "context_recall": context_recall,
    }
    outcome = asyncio.run(run_eval(tenant=tenant, module=module, thresholds=thresholds))
    means = ", ".join(f"{name}={value:.4f}" for name, value in sorted(outcome.means.items()))
    status = "PASS" if outcome.passed else f"FAIL: below threshold - {', '.join(outcome.failures)}"
    typer.echo(f"RAGAS run {outcome.run_id}: {outcome.sample_count} sample(s) - {means} - {status}")
    if not outcome.passed:
        raise typer.Exit(1)


@app.command()
def sweep_caches() -> None:
    """Purge expired ai_query_cache rows for every tenant (SKY-58)."""
    import asyncio

    from ai_agent.sweep import sweep_expired_query_cache

    deleted = asyncio.run(sweep_expired_query_cache())
    typer.echo(f"Deleted {deleted} expired query cache row(s).")


if __name__ == "__main__":
    app()
