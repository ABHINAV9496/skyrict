"""Benchmark entrypoint - ``python -m benchmarks.run``.

Runs the SKY-99 case set against real Postgres, enforces the budgets in
``thresholds.json``, and writes a markdown report. Exits non-zero when any
case fails its gates, so CI can use this as a hard regression gate.

``--samples``/``--warmup`` override the defaults so local runs can get a
quick read; CI uses the defaults for stable statistics.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from benchmarks.harness import Case, StatementMonitor, load_budgets, run_case
from benchmarks.scenarios import (
    cashflow_naive_loop,
    cashflow_projection_case,
    destroy_benchmark_world,
    duplicates_case,
    report_aggregate_recompute,
    report_cache_hit_case,
    report_cache_miss_case,
    seed_benchmark_world,
    seed_cache_hit,
    working_capital_serial,
    working_capital_series_case,
)
from core.db.session import async_session_factory, engine

_DEFAULT_BUDGETS = Path(__file__).resolve().parent / "thresholds.json"
_DEFAULT_OUT = Path(__file__).resolve().parent / "results" / "core.md"


def _case_specs() -> dict[str, str]:
    """Name -> short reusable label for the report table."""
    return {
        "duplicates": "Duplicates windowed scan",
        "cashflow_projection": "Cashflow projection (monthly aggregate)",
        "cashflow_naive_loop": "Cashflow - 6 month queries (reference)",
        "working_capital_series": "Working capital series (6 parallel forks)",
        "working_capital_serial": "Working capital - 6 serial queries (reference)",
        "report_cache_hit": "Report cache hit",
        "report_aggregate_recompute": "Report recompute (uncached)",
        "report_cache_miss": "Report cache miss",
    }


def _budget_for(budgets: dict[str, dict[str, float | int]], name: str) -> dict[str, float | int]:
    spec = budgets.get(name)
    if spec is None:
        raise SystemExit(
            f"budgets: no gate defined for case '{name}'. A renamed scenario must "
            "not silently drop its gate - add it to thresholds.json."
        )
    return spec


async def _expect_db() -> None:
    """Fail fast with a useful message when the benchmark DB is unreachable."""
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT count(*) FROM alembic_version"))
    except SQLAlchemyError as exc:  # pragma: no cover - needs a down DB
        raise SystemExit(
            f"cannot reach the core database ({engine.url.host}:{engine.url.port}): "
            f"{exc.__class__.__name__}: {exc}"
        ) from exc


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Skyrict core benchmark gate")
    parser.add_argument("--budgets", type=Path, default=_DEFAULT_BUDGETS)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--warmup", type=int, default=3)
    args = parser.parse_args(argv)

    await _expect_db()
    budgets = load_budgets(args.budgets)

    world = await seed_benchmark_world()
    tenant_id = world["tenant_id"]
    await seed_cache_hit(world)

    monitor = StatementMonitor(engine.sync_engine)
    monitor.attach()

    def _mk_case(name: str, fn: Any, reference: Any = None) -> Case:
        spec = _budget_for(budgets, name)
        ratio = spec.get("reference_ratio")
        return Case(
            name=name,
            fn=fn,
            p95_ms=float(spec.get("p95_ms", 0)) if "p95_ms" in spec else None,
            max_queries=int(spec["max_queries"]),
            reference=reference if ratio is not None else None,
            reference_ratio=float(ratio) if ratio is not None else None,
            warmup=args.warmup,
            samples=args.samples,
        )

    cases = [
        _mk_case("duplicates", duplicates_case(tenant_id)),
        _mk_case(
            "cashflow_projection",
            cashflow_projection_case(tenant_id),
            reference=cashflow_naive_loop(tenant_id),
        ),
        _mk_case(
            "cashflow_naive_loop",
            cashflow_naive_loop(tenant_id),
        ),
        _mk_case(
            "working_capital_series",
            working_capital_series_case(tenant_id),
            reference=working_capital_serial(tenant_id),
        ),
        _mk_case("working_capital_serial", working_capital_serial(tenant_id)),
        _mk_case(
            "report_cache_hit",
            report_cache_hit_case(tenant_id),
            reference=report_aggregate_recompute(tenant_id),
        ),
        _mk_case("report_aggregate_recompute", report_aggregate_recompute(tenant_id)),
        _mk_case("report_cache_miss", report_cache_miss_case(tenant_id)),
    ]

    results = []
    try:
        for case in cases:
            results.append(await run_case(case, monitor))
    finally:
        monitor.detach()
        await destroy_benchmark_world(world)

    failures = [r for r in results if not r.ok]
    passed = [r for r in results if r.ok]

    table = [
        "| Case | p95 (ms) | median (ms) | work stmts (med/max) | ref p95 (ms) | status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        ref = f"{r.reference_p95_ms:.1f}" if r.reference_p95_ms is not None else "-"
        status = "PASS" if r.ok else "FAIL"
        table.append(
            f"| {r.name} | {r.p95_ms:.1f} | {r.median_ms:.1f} | "
            f"{r.median_queries}/{r.max_queries_observed} | {ref} | {status} |"
        )

    header = [
        "# SKY-99 backend performance gates",
        "",
        f"- run: {datetime.now(UTC).isoformat()}",
        f"- samples: {args.samples}, warmup: {args.warmup}",
        f"- passed: {len(passed)}/{len(results)}",
        "",
    ]
    detail_lines = []
    for r in results:
        detail_lines.append(f"- `{r.name}`: {r.detail}")
    report = "\n".join(header + table + [""] + detail_lines + [""])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(report)

    if failures:
        print(
            f"[!] FAILED {len(failures)} gate(s); report written to {args.out}\n", file=sys.stderr
        )
        return 1
    print(f"all gates passed; report written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
