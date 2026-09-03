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

Advisory checks (``warnings`` — never abort a batch, only reported):

* ``banking`` — roster employees missing bank details (the payslip/notify
  payload fields from Commit 1).
* ``benefit_elections`` — roster employees holding no ``enrolled`` benefit
  election for the period (reads the Commit 2.5 benefit elections).
* ``termination`` — roster employees flagged active yet carrying a termination
  date (data inconsistency). Employees *terminated during the period* are, by
  payroll design, legitimately on the roster (Rule 9 prorates their pay) and
  are NOT flagged.

The module is intentionally free of IO and ORM imports beyond the domain
entities, so it is unit-testable in isolation.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core.core.constants import EmploymentStatus
from core.domain.entities import BenefitElection, Employee, PayrollRun, PayrollSettings
from core.features.payroll.models.payroll_run import PayrollRunStatus

PREFLIGHT_VERSION = 2


@dataclass(frozen=True)
class PreflightResult:
    """Outcome of a pre-flight pass — persisted as the batch's JSONB ``preflight``."""

    run_id: str
    checks: dict[str, dict[str, str]]
    blocks: list[str]
    warnings: list[str]
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
            "warnings": list(self.warnings),
        }


def _check(*, ok: bool, detail: str) -> dict[str, str]:
    return {"status": "ok" if ok else "block", "detail": detail}


def _warn(detail: str) -> dict[str, str]:
    return {"status": "warn", "detail": detail}


def _joiner(values: Sequence[str]) -> str:
    return ", ".join(values)


def run_preflight(
    *,
    run: PayrollRun,
    settings: PayrollSettings | None,
    overlapping: PayrollRun | None,
    roster: Sequence[Employee],
    elections: Sequence[BenefitElection] | None = None,
) -> PreflightResult:
    """Validate a run before batch processing; never performs IO.

    ``overlapping`` is the winner returned by the payroll feature's
    :meth:`PayrollService.find_overlapping_run` for the run's period, or
    ``None`` (the run's own period normally maps back to the run itself).
    ``elections`` are the tenant's enrolled benefit elections effective by the
    run's period end (pre-flight input, gathered by the caller).
    """
    checks: dict[str, dict[str, str]] = {}
    blocks: list[str] = []
    warnings: list[str] = []

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

    # ---- advisory checks (warnings; never abort) ----

    # banking: payslip payload fields missing on a roster employee
    missing_bank = [e.employee_number for e in roster if not (e.bank_account or "").strip()]
    if missing_bank:
        warnings.append("banking")
        checks["banking"] = _warn(
            f"{len(missing_bank)} employee(s) missing bank details: {_joiner(missing_bank)}"
        )
    else:
        checks["banking"] = _check(ok=True, detail="all roster employees have bank details")

    # benefit_elections: no enrolled election effective for the period
    elected: dict[uuid.UUID, int] = {}
    for election in elections or ():
        elected[election.employee_id] = elected.get(election.employee_id, 0) + 1
    no_election = [
        e.employee_number for e in roster if e.id is not None and elected.get(e.id, 0) == 0
    ]
    if no_election:
        warnings.append("benefit_elections")
        checks["benefit_elections"] = _warn(
            f"{len(no_election)} employee(s) with no enrolled benefit election: {_joiner(no_election)}"
        )
    else:
        checks["benefit_elections"] = _check(
            ok=True, detail="all roster employees hold an enrolled benefit election"
        )

    # termination: active flag vs termination date inconsistency. Deliberately
    # NOT the terminated-during-period case — those employees are on the roster
    # by payroll design (Rule 9) and are never flagged.
    flagged = [
        e.employee_number
        for e in roster
        if e.employment_status is EmploymentStatus.ACTIVE and e.termination_date is not None
    ]
    if flagged:
        warnings.append("termination")
        checks["termination"] = _warn(
            f"{len(flagged)} active employee(s) flagged with a termination date: {_joiner(flagged)}"
        )
    else:
        checks["termination"] = _check(
            ok=True, detail="no active employee is flagged with a termination date"
        )

    return PreflightResult(
        run_id=str(run.id),
        checks=checks,
        blocks=blocks,
        warnings=warnings,
        roster_count=len(roster),
    )


__all__ = ["PREFLIGHT_VERSION", "PreflightResult", "run_preflight"]
