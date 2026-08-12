"""CLI entrypoint for the Core service."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

# services/core — the alembic.ini lives here; the CLI is invoked via
# `uv run --directory services/core core ...`, so never resolve relative to
# the process CWD (which is already services/core, making a nested path).
# cli.py lives at services/core/src/core/, so parents[2] is services/core.
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]

app = typer.Typer(name="core", help="Skyrict Core Service CLI")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(8001, help="Bind port"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload"),
    log_level: str = typer.Option("info", help="Log level"),
) -> None:
    """Start the Core service."""
    import uvicorn

    uvicorn.run(
        "core.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


@app.command()
def migrate(head: str = typer.Option("head", help="Alembic target revision")) -> None:
    """Run database migrations (version table: alembic_version_core)."""
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", head],
        cwd=_PACKAGE_ROOT,
        check=True,
    )


@app.command()
def seed() -> None:
    """Verify reference data seeded by migration 0001 (currencies, permissions).

    Core's reference data (erp_currencies, core_permissions) is seeded by the
    migration itself, so this command only reports that the expected rows are
    present — it is intentionally idempotent.
    """
    import asyncio

    from sqlalchemy import func, select

    from core.db.session import async_session_factory
    from core.models.core_permission import CorePermissionModel
    from core.models.erp_currency import ErpCurrencyModel

    async def _verify() -> None:
        async with async_session_factory() as session:
            currency_count = (
                await session.execute(select(func.count()).select_from(ErpCurrencyModel))
            ).scalar_one()
            permission_count = (
                await session.execute(select(func.count()).select_from(CorePermissionModel))
            ).scalar_one()
            typer.echo(f"erp_currencies: {currency_count} rows")
            typer.echo(f"core_permissions: {permission_count} rows")

    asyncio.run(_verify())


if __name__ == "__main__":
    app()
