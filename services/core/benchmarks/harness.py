"""``core`` performance benchmark harness (SKY-99 regression gates).

A tiny self-contained runner (no pytest, no pytest-benchmark) that:

- runs each guarded scenario ``samples`` times against REAL Postgres,
- tracks the number of *work* SQL statements each sampled run issued
  (transaction/tenant setup statements like ``BEGIN``/``SET LOCAL`` are
  excluded), so an N+1 loop regression fails deterministically,
- records wall-clock milliseconds per run and derives p95,
- enforces the budgets in a thresholds JSON (absolute p95 ceilings are
  deliberately generous "catastrophic regression" budgets; the statement
  counts and the reference comparisons are the real guards),
- optionally compares a case against a *reference* implementation (the
  pre-optimization query pattern) and fails if the optimized path is not
  materially faster.

Statement counting works through the one shared async engine, so it also
catches the SKY-99 forked-session reads (``parallel_reads``) - every forked
session shares the same sync engine event listener.
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import event

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from sqlalchemy.engine import Engine

# setup statements that do no application work and are excluded from counts
_NON_WORK_PREFIXES = (
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "SAVEPOINT",
    "RELEASE",
    "SET LOCAL",
    "SELECT set_config",
    "SELECT pg_advisory_lock",
    "SELECT pg_advisory_unlock",
)


def _is_work(sql: str) -> bool:
    stripped = sql.strip()
    return not stripped.startswith(_NON_WORK_PREFIXES)


class StatementMonitor:
    """Count work statements on the shared engine via ``before_cursor_execute``."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._count = 0

    def attach(self) -> None:
        event.listen(self._engine, "before_cursor_execute", self)

    def detach(self) -> None:
        event.remove(self._engine, "before_cursor_execute", self)

    def reset(self) -> None:
        self._count = 0

    @property
    def count(self) -> int:
        return self._count

    def __call__(
        self,
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if _is_work(statement):
            self._count += 1


@dataclass(frozen=True)
class Case:
    """One benchmarked scenario plus its gates."""

    name: str
    fn: Callable[[], Awaitable[object]]
    p95_ms: float | None = None
    max_queries: int | None = None
    reference: Callable[[], Awaitable[object]] | None = None
    reference_ratio: float | None = None
    warmup: int = 3
    samples: int = 8


@dataclass
class CaseResult:
    name: str
    p95_ms: float
    median_ms: float
    median_queries: int
    max_queries_observed: int
    reference_p95_ms: float | None
    ok: bool
    detail: str


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    return ordered[min(n - 1, max(0, int(0.95 * (n - 1))))]


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


async def _sample(
    monitor: StatementMonitor,
    fn: Callable[[], Awaitable[object]],
    count: int,
) -> tuple[list[float], list[int]]:
    times: list[float] = []
    queries: list[int] = []
    for _ in range(count):
        monitor.reset()
        start = time.perf_counter()
        await fn()
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        times.append(elapsed_ms)
        queries.append(monitor.count)
    return times, queries


async def run_case(case: Case, monitor: StatementMonitor) -> CaseResult:
    """Run warmup + samples and evaluate the case's gates."""
    await _sample(monitor, case.fn, case.warmup)
    times, query_counts = await _sample(monitor, case.fn, case.samples)

    reference_p95: float | None = None
    if case.reference is not None:
        await _sample(monitor, case.reference, case.warmup)
        ref_times, _ = await _sample(monitor, case.reference, case.samples)
        reference_p95 = _p95(ref_times)

    p95 = _p95(times)
    max_q = max(query_counts)
    ok = True
    failures: list[str] = []

    if case.p95_ms is not None and p95 > case.p95_ms:
        ok = False
        failures.append(f"p95 {p95:.1f}ms exceeds budget {case.p95_ms}ms")
    if case.max_queries is not None and max_q > case.max_queries:
        ok = False
        failures.append(
            f"max work statements {max_q} exceeds budget {case.max_queries} (N+1 loop regression?)"
        )
    if case.reference is not None and reference_p95 is not None:
        ratio = case.reference_ratio or 0.95
        if p95 >= reference_p95 * ratio:
            ok = False
            failures.append(
                f"p95 {p95:.1f}ms is not materially faster than reference "
                f"{reference_p95:.1f}ms (needs < {ratio:.2f}x)"
            )

    detail = "; ".join(failures) if failures else "ok"
    return CaseResult(
        name=case.name,
        p95_ms=p95,
        median_ms=statistics.median(times),
        median_queries=_median(query_counts),
        max_queries_observed=max_q,
        reference_p95_ms=reference_p95,
        ok=ok,
        detail=detail,
    )


def load_budgets(path: Path) -> dict[str, dict[str, float | int]]:
    """Load the gate budgets for every case; keys are case names.

    Unknown keys are tolerated (forward-compat); the runner validates that
    every case it registers exists in the budgets file so a renamed scenario
    cannot silently drop its gate.
    """
    if not path.exists():
        raise FileNotFoundError(f"budgets file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, dict):
        raise ValueError("budgets file must be a JSON object keyed by case name")
    budgets: dict[str, dict[str, float | int]] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise ValueError(f"budget for {name!r} must be an object")
        converted: dict[str, float | int] = {}
        for key, value in spec.items():
            if key == "max_queries":
                converted[key] = int(value)
            else:
                converted[key] = float(value)
        budgets[str(name)] = converted
    return budgets
