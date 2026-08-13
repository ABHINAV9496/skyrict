"""CLI entrypoint for the Identity service."""

from __future__ import annotations

import typer

app = typer.Typer(name="identity", help="Skyrict Identity Service CLI")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload"),
    log_level: str = typer.Option("info", help="Log level"),
) -> None:
    """Start the Identity service."""
    import uvicorn

    uvicorn.run(
        "identity.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


@app.command()
def migrate(head: str = typer.Option("head", help="Alembic target revision")) -> None:
    """Run database migrations."""
    import subprocess
    from pathlib import Path

    service_root = Path(__file__).resolve().parents[2]
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", head],
        cwd=service_root,
        check=True,
    )


@app.command()
def seed() -> None:
    """Load reference data (default tenant, roles, admin user)."""
    import asyncio

    from identity.seed import run_seed

    asyncio.run(run_seed())


if __name__ == "__main__":
    app()
