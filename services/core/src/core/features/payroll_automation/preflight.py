"""Pre-flight validation for payroll automation batches (HR-AUT-001, Commit 2).

Pure, DB-free checks that run at enqueue time (and on every dry-run) to decide
whether a payroll run MAY be batch-processed. The result is stored verbatim in
the batch's ``preflight`` JSONB column, so every submission carries its own
evidence of the check outcome.

A failing block check (these checks are all hard blocks) stops the batch: the
row is created, the preflight is stored, then the batch is finalized
immediately as ``aborted`` — no items enqueued, no compute ever started.

The checks cover the pre-flight acceptance scrub:

* ``settings`` — the tenant has its one payroll settings row.
* ``automation_enabled`` — the tenant allows the automation engine
  (``erp_payroll_settings.ai_automation_enabled``).
* ``run`` — the run is still recomputable (draft/computed), so an
  approved/paid/void run can never be claimed for processing.
* ``period`` — no *other* non-void run covers the run's period (a winning run
  already exists for the pay period). The run's own period is, by definition,
  allowed (recompute).
* ``roster`` — at least one active employee exists for the period; the roster
  query itself is the existence/active check (filters employment status, hire
  and termination dates).

The module is intentionally free of IO and ORM imports beyond the domain
entities, so it is unit-testable in isolation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core.domain.entities import Employee, PayrollRun, PayrollSettings
from core.features.payroll.models.payroll_run import PayrollRunStatus

PREFLIGHT_VERSION = 1


@dataclass(frozen=True)
class PreflightResult:
    """Outcome of a pre-flight pass — persisted as the batch's JSONB ``preflight``."""

    run_id: str
    checks: dict[str, dict[str, str]]
    blocks: list[str]
    roster_count: int

    @property
    def passed(self) -> bool:
        return not self.blocks

    def to_json(self) -> dict[str, Any]:
        return {
            "version": PREFLIGHT_VERSION,
            "passed": self.passed,
            "checked_at": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "roster_count": self.roster_count,
            "checks": self.checks,
            "blocks": list(self.blocks),
        }


def _check(*, ok: bool, detail: str) -> dict[str, str]:
    return {"status": "ok" if ok else "block", "detail": detail}


def run_preflight(
    *,
    run: PayrollRun,
    settings: PayrollSettings | None,
    overlapping: PayrollRun | None,
    roster: Sequence[Employee],
) -> PreflightResult:
    """Validate a run before batch processing; never performs IO.

    ``overlapping`` is the winner returned by the payroll feature's
    :meth:`PayrollService.find_overlapping_run` for the run's period, or
    ``None`` (the run's own period normally maps back to the run itself).
    """
    checks: dict[str, dict[str, str]] = {}
    blocks: list[str] = []

    # settings row present
    settings_ok = settings is not None
    checks["settings"] = _check(
        ok=settings_ok,
        detail="settings row present" if settings_ok else "no payroll settings row for tenant",
    )
    if not settings_ok:
        blocks.append("settings")

    # automation enabled on the tenant's settings
    automation_ok = settings is not None and settings.ai_automation_enabled
    checks["automation_enabled"] = _check(
        ok=automation_ok,
        detail="automation enabled" if automation_ok else "ai_automation_enabled is off",
    )
    if not automation_ok:
        blocks.append("automation_enabled")

    # run still recomputable (draft/computed)
    run_ok = run.status in (PayrollRunStatus.DRAFT, PayrollRunStatus.COMPUTED)
    checks["run"] = _check(ok=run_ok, detail=f"run is {run.status.value}")
    if not run_ok:
        blocks.append("run")

    # period not already won by another run
    if overlapping is None or overlapping.id == run.id:
        period_ok = True
        period_detail = "no other run covers this period"
    else:
        period_ok = False
        period_detail = f"run {overlapping.run_code} already covers this period"
    checks["period"] = _check(ok=period_ok, detail=period_detail)
    if not period_ok:
        blocks.append("period")

    # roster: the active-employee existence/active check + an advisory count
    roster_ok = len(roster) > 0
    checks["roster"] = _check(
        ok=roster_ok,
        detail=(
            f"{len(roster)} active employee(s) for the period"
            if roster_ok
            else "no active employees for the period"
        ),
    )
    if not roster_ok:
        blocks.append("roster")

    return PreflightResult(
        run_id=str(run.id),
        checks=checks,
        blocks=blocks,
        roster_count=len(roster),
    )


__all__ = ["PREFLIGHT_VERSION", "PreflightResult", "run_preflight"]
