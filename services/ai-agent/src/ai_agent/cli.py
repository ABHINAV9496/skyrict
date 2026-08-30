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


inventory_app = typer.Typer(
    name="inventory",
    help="Inventory semantic snapshot maintenance (SKY-70).",
    no_args_is_help=True,
)


@inventory_app.command("reindex")
def inventory_reindex(
    tenant: str = typer.Option(..., help="tenant slug or UUID (required)"),
    mode: str = typer.Option(
        "full", help="'full' wipes then rebuilds; 'incremental' only upserts the fetched catalog"
    ),
) -> None:
    """Rebuild one tenant's product embedding snapshot (SKY-70).

    Pulls the current catalog from core and (re)embeds every product into
    ai_inv_item_embeddings. ``full`` clears the tenant's snapshot first so
    deactivated-or-removed products disappear from semantic search.

    Requires an embedding provider (AI_EMBEDDING_PROVIDER + key) and
    AI_INGEST_TOKEN for the core pull.
    """
    import asyncio

    from ai_agent.inventory_reindex import run_inventory_reindex

    asyncio.run(run_inventory_reindex(tenant=tenant, mode=mode))


app.add_typer(inventory_app)


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


@app.command()
def eval_hr_models(
    config: str = typer.Option(
        str(_PACKAGE_ROOT / "tests" / "eval" / "hr_models.yaml"),
        "--config",
        help="path to the HR model eval registry (YAML)",
    ),
    model_path: str = typer.Option(
        "", "--model-path", help="model artifact path (default: bundled default)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="compute + print only; do not persist to core"
    ),
    core_url: str = typer.Option(
        "", "--core-url", envvar="SKYRICT_CORE_URL", help="core service base URL"
    ),
    token: str = typer.Option(
        "", "--token", envvar="SKYRICT_CORE_TOKEN", help="bearer token with erp.hr.ai.eval"
    ),
    tenant_slug: str = typer.Option(
        "", "--tenant-slug", envvar="SKYRICT_TENANT_SLUG", help="tenant slug for the eval run"
    ),
) -> None:
    """Evaluate the deployed HR models against the labeled seed sets (SKY-72).

    Prints one line per metric, WARNS (never fails) when precision is below
    the documented 0.70 threshold, and posts the results to core's
    ``/api/v1/ai/hr/eval-runs`` endpoint for the historical record. Redact-safe:
    seed rows carry features + labels only, never employee PII.
    """
    import asyncio

    from ai_agent.eval.harness import post_eval_runs, run_registry, to_payload

    results = run_registry(config, model_path=model_path or None)
    for metric in results:
        verdict = "PASS" if metric.met_threshold else "WARN"
        typer.echo(
            f"[{verdict}] {metric.model_name}:{metric.metric} "
            f"precision={metric.precision:.4f} "
            f"(considered={metric.considered}, abstained={metric.abstained}, "
            f"threshold={metric.threshold:.2f}, source={metric.model_source}, "
            f"version={metric.model_version})"
        )
    underperforming = [m for m in results if not m.met_threshold]
    for metric in underperforming:
        typer.echo(
            f"WARNING {metric.model_name}:{metric.metric} precision "
            f"{metric.precision:.4f} < {metric.threshold:.2f}",
            err=True,
        )

    if dry_run:
        typer.echo("dry-run: results not persisted")
        return
    if not (core_url and token and tenant_slug):
        typer.echo(
            "SKIPPED persistence: pass --core-url/--token/--tenant-slug "
            "(or SKYRICT_CORE_URL/TOKEN/TENANT_SLUG) to record results",
            err=True,
        )
        return

    rows = [to_payload(metric) for metric in results]
    try:
        asyncio.run(post_eval_runs(core_url, token, tenant_slug, rows))
    except Exception as exc:  # warn-not-fail: an eval is never a hard gate
        typer.echo(f"WARNING failed to persist eval results: {exc}", err=True)
        return
    typer.echo(f"recorded {len(rows)} eval metric(s) -> {core_url}")


if __name__ == "__main__":
    app()
