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
def attrition_train(
    dataset: str = typer.Option(
        "", "--dataset", help="optional CSV (see features/attrition/cli.py)"
    ),
    version: str = typer.Option("v1-gbc-2026-08", "--version"),
    output: str = typer.Option(
        "", "--output", help="artifact path (default: bundled artifacts dir)"
    ),
    max_depth: int = typer.Option(3, "--max-depth"),
    estimators: int = typer.Option(40, "--estimators"),
) -> None:
    """Manually train + export the HR attrition GBC model (spec §6 cadence)."""
    from ai_agent.features.attrition.cli import train as attrition_train_cmd

    out = output or str(
        _PACKAGE_ROOT / "src" / "ai_agent" / "features" / "attrition" / "artifacts" / "model.joblib"
    )
    attrition_train_cmd(
        dataset=dataset,
        version=version,
        output=out,
        max_depth=max_depth,
        estimators=estimators,
    )


if __name__ == "__main__":
    app()
