"""Pure leave-pattern anomaly rules shared by core and the eval harness.

HR-AI-002 §8.2.1 — the leave-pattern anomaly inbox.  This module is pure
(no SQLAlchemy, no I/O, stdlib only) so that the engine deployed in
:mod:`core.features.ai_hr.anomaly_repository` and the ai-agent eval harness
(``anomaly_precision``, SKY-72) run the LITERAL same detection code.

Every rule is gated by a *team-size gate*: a team with fewer than
``min_team_size`` active members is abstained entirely (thin baselines never
emit findings), and the median-comparison rules also require the team median
to be measurable:

- ``leave_overuse``: an employee's trailing total leave days >= ``spike_ratio``
  x the team median days (median >= 1).
- ``frequent_absence``: an employee's request count >= ``spike_ratio`` x the
  team median count (median >= 1).
- ``short_notice_monday_friday``: one request whose span touches a Monday or
  Friday, was filed fewer than ``short_notice_days`` before it starts, AND is
  at ``spike_ratio`` x the team median days.
- ``pre_holiday_spike``: one request whose span sits within
  ``pre_holiday_adjacency_days`` of a public holiday (org-wide or scoped to the
  team's department) AND is at ``spike_ratio`` x the team median days.

Severity scaling: overuse/frequent use the ratio bands (>= 5 critical,
>= 4 high, else medium); short-notice is high when filed within
``short_notice_pressing_days``; pre-holiday is high when the request overlaps
the holiday date, else medium.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping, Sequence

_FINDING_TITLES: dict[str, str] = {
    "leave_overuse": "Above-average leave consumption",
    "frequent_absence": "Frequent leave requests",
    "short_notice_monday_friday": "Short-notice leave on a Monday/Friday",
    "pre_holiday_spike": "Leave clustered around a public holiday",
}


@dataclass(frozen=True, slots=True)
class RequestSignal:
    """One leave request as the rules see it (projected from the ORM row)."""

    request_id: uuid.UUID
    employee_id: uuid.UUID
    start_date: date
    end_date: date
    days: int
    leave_type: str
    filed_on: date


@dataclass(frozen=True, slots=True)
class Holiday:
    """One public holiday / office-closure day (or department-scoped)."""

    calendar_date: date
    name: str
    department_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class AnomalyFinding:
    """One computed finding; the ORM layer maps this onto its row shape."""

    employee_id: uuid.UUID
    anomaly_type: str
    severity: str
    title: str
    description: str
    team_id: uuid.UUID | None
    team_size: int
    evidence: dict[str, Any] = field(default_factory=dict)


def ratio_severity(ratio: float) -> str:
    """Map a ratio to the documented severity band."""
    if ratio >= 5:
        return "critical"
    if ratio >= 4:
        return "high"
    return "medium"


def _distance_to_span(span_start: date, span_end: date, day: date) -> int:
    """Minimum day distance from ``day`` to the inclusive span ``[start, end]``."""
    if day < span_start:
        return (span_start - day).days
    if day > span_end:
        return (day - span_end).days
    return 0


def detect_leave_pattern_anomalies(
    *,
    members: Mapping[uuid.UUID | None, Sequence[uuid.UUID]],
    requests_by_employee: Mapping[uuid.UUID, Sequence[RequestSignal]],
    holidays: Sequence[Holiday] = (),
    today: date,
    trailing_days: int = 90,
    min_team_size: int = 4,
    spike_ratio: float = 3.0,
    short_notice_days: int = 14,
    short_notice_pressing_days: int = 3,
    pre_holiday_adjacency_days: int = 2,
) -> list[AnomalyFinding]:
    """Run every rule over one tenant's teams and return the findings.

    ``members`` groups active employees by department; ``requests`` maps each
    employee to their requests (only approved/pending need be passed, but the
    engine re-filters to the trailing window so callers can pass more). Inputs
    are immutable (read-only); the caller owns persistence.
    """
    window_start = today - timedelta(days=trailing_days)
    findings: list[AnomalyFinding] = []

    for team_id, member_ids in members.items():
        if len(member_ids) < min_team_size:
            continue  # team-size gate: abstain for thin baselines
        team_holidays = [
            h for h in holidays if h.department_id is None or h.department_id == team_id
        ]

        days_by: dict[uuid.UUID, int] = {}
        count_by: dict[uuid.UUID, int] = {}
        windowed: dict[uuid.UUID, list[RequestSignal]] = {}
        for mid in member_ids:
            windowed[mid] = [
                r
                for r in requests_by_employee.get(mid, ())
                if window_start <= r.start_date <= today
            ]
            days_by[mid] = sum(r.days for r in windowed[mid])
            count_by[mid] = len(windowed[mid])

        med_days = median(days_by.values())
        med_count = median(count_by.values())

        for mid in member_ids:
            member_reqs = windowed[mid]
            if not member_reqs:
                continue
            total_days = days_by[mid]
            count = count_by[mid]
            first_start = min(rq.start_date for rq in member_reqs).isoformat()

            # leave_overuse: trailing days >= 3x team median days.
            if med_days >= 1 and total_days >= spike_ratio * med_days:
                ratio = total_days / med_days
                findings.append(
                    AnomalyFinding(
                        employee_id=mid,
                        anomaly_type="leave_overuse",
                        severity=ratio_severity(ratio),
                        title=_FINDING_TITLES["leave_overuse"],
                        description=(
                            f"{total_days} leave day(s) used in the trailing "
                            f"{trailing_days} days vs a team median of "
                            f"{med_days:.1f}."
                        ),
                        team_id=team_id,
                        team_size=len(member_ids),
                        evidence={
                            "window_days": trailing_days,
                            "leave_days": total_days,
                            "team_median_days": round(med_days, 2),
                            "request_count": count,
                            "first_start": first_start,
                        },
                    )
                )

            # frequent_absence: request count >= 3x team median count.
            if med_count >= 1 and count >= spike_ratio * med_count:
                ratio = count / med_count
                findings.append(
                    AnomalyFinding(
                        employee_id=mid,
                        anomaly_type="frequent_absence",
                        severity=ratio_severity(ratio),
                        title=_FINDING_TITLES["frequent_absence"],
                        description=(
                            f"{count} leave request(s) in the trailing "
                            f"{trailing_days} days vs a team median of "
                            f"{med_count:.1f}."
                        ),
                        team_id=team_id,
                        team_size=len(member_ids),
                        evidence={
                            "window_days": trailing_days,
                            "request_count": count,
                            "team_median_count": round(med_count, 2),
                            "leave_days": total_days,
                        },
                    )
                )

            if med_days < 1:
                continue  # magnitude-based rules need a measurable median

            for rq in member_reqs:
                # short_notice_monday_friday: Mon/Fri span filed on short notice
                # and long relative to the team (a conspicuous "block").
                touches_fringe = rq.start_date.weekday() in (0, 4) or (
                    rq.end_date.weekday() in (0, 4)
                )
                advance = (rq.start_date - rq.filed_on).days
                if (
                    rq.days >= spike_ratio * med_days
                    and touches_fringe
                    and 0 <= advance < short_notice_days
                ):
                    severity = "high" if advance <= short_notice_pressing_days else "medium"
                    findings.append(
                        AnomalyFinding(
                            employee_id=mid,
                            anomaly_type="short_notice_monday_friday",
                            severity=severity,
                            title=_FINDING_TITLES["short_notice_monday_friday"],
                            description=(
                                f"Short-notice leave touching a Monday/Friday: "
                                f"{rq.days} day(s) from {rq.start_date} to "
                                f"{rq.end_date} filed {advance} day(s) ahead vs "
                                f"a team median of {med_days:.1f} day(s)."
                            ),
                            team_id=team_id,
                            team_size=len(member_ids),
                            evidence={
                                "request_id": str(rq.request_id),
                                "window_days": trailing_days,
                                "request_days": rq.days,
                                "team_median_days": round(med_days, 2),
                                "advance_days": advance,
                                "start_date": rq.start_date.isoformat(),
                                "end_date": rq.end_date.isoformat(),
                            },
                        )
                    )

                # pre_holiday_spike: span near a holiday and long vs the median.
                if rq.days >= spike_ratio * med_days and team_holidays:
                    nearest: tuple[int, Holiday] | None = None
                    for holiday in team_holidays:
                        distance = _distance_to_span(
                            rq.start_date, rq.end_date, holiday.calendar_date
                        )
                        if nearest is None or distance < nearest[0]:
                            nearest = (distance, holiday)
                    assert nearest is not None
                    distance, holiday = nearest
                    if distance <= pre_holiday_adjacency_days:
                        severity = "high" if distance == 0 else "medium"
                        findings.append(
                            AnomalyFinding(
                                employee_id=mid,
                                anomaly_type="pre_holiday_spike",
                                severity=severity,
                                title=_FINDING_TITLES["pre_holiday_spike"],
                                description=(
                                    f"Leave within {distance} day(s) of "
                                    f"{holiday.name} ({holiday.calendar_date}): "
                                    f"{rq.days} day(s) vs a team median of "
                                    f"{med_days:.1f}."
                                ),
                                team_id=team_id,
                                team_size=len(member_ids),
                                evidence={
                                    "request_id": str(rq.request_id),
                                    "window_days": trailing_days,
                                    "request_days": rq.days,
                                    "team_median_days": round(med_days, 2),
                                    "start_date": rq.start_date.isoformat(),
                                    "end_date": rq.end_date.isoformat(),
                                    "holiday_date": holiday.calendar_date.isoformat(),
                                    "holiday_name": holiday.name,
                                    "distance_days": distance,
                                },
                            )
                        )

    return findings


# ---------------------------------------------------------------------------
# Payroll anomaly rules (HR-AI-001 Unit B) — detection only, no I/O.
#
# The ``ai_payroll_anomaly_log`` table and its three anomaly types are defined
# up front (Commit 4 table); the ENGINE lives here so core and the ai-agent
# eval harness run the literal same code. Every finding must stay anonymous in
# ``evidence``: bank accounts are masked to the last four digits, never full
# numbers, and no name/number/email is ever written by the rules.
#
# Rules (latest-non-void-run scan, delta vs the immediately preceding run):
#   - ``net_pay_delta``: an employee's net-per-payday in the latest run
#     departs from their PRECEDING run by >= ``delta_ratio`` (>= 5x critical,
#     >= 4x high, else medium via :func:`ratio_severity`).
#   - ``duplicate_account``: the same payout account is shared by 2+ distinct
#     employees in the latest run. Medium for 2, high for 3+, critical when a
#     terminated employee is in the group. Row ``employee_id`` = the group's
#     highest-net member (deterministic); all members are in ``evidence``.
#   - ``ghost_employee``: the latest run pays an employee who is terminated
#     (critical) or who has NO bank account on file (medium).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PayrollEntrySignal:
    """One payroll-entry row as the rules see it (projected from ORM)."""

    employee_id: uuid.UUID
    run_code: str
    period_start: date
    period_end: date
    base_salary: float
    pay_days: int
    gross: float
    deductions: float
    net: float


@dataclass(frozen=True, slots=True)
class PayrollEmployeeContext:
    """HR facts about one employee needed by the payroll rules."""

    employee_id: uuid.UUID
    status: str
    bank_account: str | None
    termination_date: date | None = None


@dataclass(frozen=True, slots=True)
class PayrollAnomalyFinding:
    """One computed payroll finding (``employee_id`` is account-level None)."""

    employee_id: uuid.UUID | None
    anomaly_type: str
    severity: str
    title: str
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)


_PAYROLL_FINDING_TITLES: dict[str, str] = {
    "net_pay_delta": "Unusual change in net pay",
    "duplicate_account": "Shared payout account",
    "ghost_employee": "Ghost employee payout",
}


def normalize_account(raw: str) -> str:
    """Uppercase, alphanumeric-only account key for duplicate comparison."""
    return "".join(ch for ch in raw if ch.isalnum()).casefold()


def mask_account(raw: str) -> str:
    """Last four digits only — never a full account number in evidence."""
    normalized = normalize_account(raw)
    if len(normalized) <= 4:
        return "****"
    return f"****{normalized[-4:]}"


def _net_per_day(entry: PayrollEntrySignal) -> float:
    return entry.net / max(entry.pay_days, 1)


def detect_payroll_anomalies(
    *,
    latest_entries: Sequence[PayrollEntrySignal],
    prior_entries: Sequence[PayrollEntrySignal],
    employees: Mapping[uuid.UUID, PayrollEmployeeContext],
    delta_ratio: float = 1.5,
) -> list[PayrollAnomalyFinding]:
    """Run every payroll rule over the latest run vs the preceding one.

    ``latest_entries``/``prior_entries`` are the two runs' entry rows (the
    caller resolves which run is "latest"); ``employees`` carries the HR facts.
    Inputs are immutable; the caller owns persistence.
    """
    latest_by_emp = {e.employee_id: e for e in latest_entries}
    prior_by_emp = {e.employee_id: e for e in prior_entries}
    latest_code = (
        latest_entries[0].run_code if latest_entries else "unknown"
    )
    findings: list[PayrollAnomalyFinding] = []

    # net_pay_delta — magnitude of the per-payday swing vs the preceding run.
    for emp_id, current in latest_by_emp.items():
        prior = prior_by_emp.get(emp_id)
        if prior is None:
            continue
        current_npd = _net_per_day(current)
        prior_npd = _net_per_day(prior)
        if prior_npd <= 0 or current_npd <= 0:
            continue
        ratio = max(current_npd, prior_npd) / min(current_npd, prior_npd)
        if ratio < delta_ratio:
            continue
        direction = "increase" if current_npd >= prior_npd else "decrease"
        findings.append(
            PayrollAnomalyFinding(
                employee_id=emp_id,
                anomaly_type="net_pay_delta",
                severity=ratio_severity(ratio),
                title=_PAYROLL_FINDING_TITLES["net_pay_delta"],
                description=(
                    f"Net pay per day changed {ratio:.2f}x ({direction}) in "
                    f"{current.run_code} against {prior.run_code}."
                ),
                evidence={
                    "current_run": current.run_code,
                    "prior_run": prior.run_code,
                    "current_net": round(current.net, 2),
                    "prior_net": round(prior.net, 2),
                    "current_pay_days": current.pay_days,
                    "prior_pay_days": prior.pay_days,
                    "ratio": round(ratio, 3),
                    "direction": direction,
                },
            )
        )

    # duplicate_account — one normalized payout account shared by 2+ employees.
    groups: dict[str, list[uuid.UUID]] = {}
    for emp_id, _current in latest_by_emp.items():
        ctx = employees.get(emp_id)
        account = (ctx.bank_account or "").strip() if ctx else ""
        if not account:
            continue
        groups.setdefault(normalize_account(account), []).append(emp_id)
    for account_key, member_ids in groups.items():
        if len(member_ids) < 2:
            continue
        members = [(emp_id, employees.get(emp_id)) for emp_id in member_ids]
        has_terminated = any(ctx is not None and ctx.status == "terminated" for _, ctx in members)
        # Deterministic primary: highest net in the current run, then uuid.
        def _net_of(emp_id: uuid.UUID, ctx: PayrollEmployeeContext | None) -> float:
            entry = latest_by_emp.get(emp_id)
            return entry.net if entry is not None else 0.0

        primary = max(
            (emp_id for emp_id, ctx in members),
            key=lambda emp_id: (_net_of(emp_id, employees.get(emp_id)), emp_id),
        )
        masked = mask_account(account_key)
        findings.append(
            PayrollAnomalyFinding(
                employee_id=primary,
                anomaly_type="duplicate_account",
                severity="critical" if has_terminated else ("high" if len(member_ids) >= 3 else "medium"),
                title=_PAYROLL_FINDING_TITLES["duplicate_account"],
                description=(
                    f"{len(member_ids)} employees share payout account "
                    f"{masked} in {latest_code}."
                ),
                evidence={
                    "account_masked": masked,
                    "employee_ids": [str(mid) for mid in member_ids],
                    "employee_count": len(member_ids),
                    "run_code": latest_code,
                    "includes_terminated": has_terminated,
                },
            )
        )

    # ghost_employee — paid while terminated, or payable with no account.
    for emp_id, current in latest_by_emp.items():
        ctx = employees.get(emp_id)
        if ctx is None:
            continue
        if ctx.status == "terminated":
            findings.append(
                PayrollAnomalyFinding(
                    employee_id=emp_id,
                    anomaly_type="ghost_employee",
                    severity="critical",
                    title=_PAYROLL_FINDING_TITLES["ghost_employee"],
                    description=(
                        f"{current.run_code} pays net {current.net} to an "
                        "employee whose employment is terminated."
                    ),
                    evidence={
                        "status": ctx.status,
                        "termination_date": (
                            ctx.termination_date.isoformat() if ctx.termination_date else None
                        ),
                        "run_code": current.run_code,
                        "net": round(current.net, 2),
                    },
                )
            )
        elif not (ctx.bank_account or "").strip():
            findings.append(
                PayrollAnomalyFinding(
                    employee_id=emp_id,
                    anomaly_type="ghost_employee",
                    severity="medium",
                    title=_PAYROLL_FINDING_TITLES["ghost_employee"],
                    description=(
                        f"{current.run_code} pays an employee who has no bank "
                        "account on file."
                    ),
                    evidence={
                        "status": ctx.status,
                        "has_bank_account": False,
                        "run_code": current.run_code,
                        "net": round(current.net, 2),
                    },
                )
            )

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(
        findings,
        key=lambda f: (
            severity_order.get(f.severity, 3),
            f.anomaly_type,
            str(f.employee_id),
        ),
    )


# --- Compliance rule pack v1 (HR-AI-001, Unit C) ------------------------------
# Checks are pure and read only the projected signals below; the caller owns
# persistence. No employee identifier or PII ever lands in ``evidence`` — only
# document types, dates, and field *names* (never field *values*).


@dataclass(frozen=True, slots=True)
class EmployeeComplianceContext:
    """HR facts about one employee needed by the compliance rules.

    ``requires_training`` marks an employee whose role mandates a current
    ``certification``; it drives the ``training_overdue`` missing-document rule.
    Field names mirror ``erp_employees`` so the engine can stay pure.
    """

    employee_id: uuid.UUID
    status: str
    email: str | None = None
    department_id: uuid.UUID | None = None
    job_title: str | None = None
    phone: str | None = None
    requires_training: bool = False


@dataclass(frozen=True, slots=True)
class DocumentComplianceSignal:
    """One ``erp_employee_documents`` row as the compliance rules see it."""

    employee_id: uuid.UUID
    document_id: uuid.UUID
    doc_type: str
    expiry_date: date | None = None
    is_required: bool = False
    status: str = "active"


@dataclass(frozen=True, slots=True)
class ComplianceFinding:
    """One computed compliance finding.

    ``owner_rule`` names the routing owner key (``hr_admin`` /
    ``compliance_officer``); ``evidence`` deliberately omits employee PII.
    """

    employee_id: uuid.UUID | None
    check_type: str
    severity: str
    owner_rule: str
    title: str
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)


# Document types whose near-/past expiry is a hard ``document_expiry`` finding.
_COMPLIANCE_EXPIRING_DOC_TYPES: frozenset[str] = frozenset(
    {"work_permit", "visa", "passport", "national_id"}
)


def _days_until(expiry: date, today: date) -> int:
    return (expiry - today).days


def detect_compliance_findings(
    *,
    documents: Sequence[DocumentComplianceSignal],
    employees: Mapping[uuid.UUID, EmployeeComplianceContext],
    today: date,
    expiry_window_days: int = 30,
) -> list[ComplianceFinding]:
    """Run the v1 compliance rule pack (Feature 4, §8 table).

    Rules:
    1. ``document_expiry`` (``compliance_officer``): a
       work_permit/visa/passport/national_id document expiring within
       ``expiry_window_days`` is ``medium``; already expired is ``high``.
    2. ``training_overdue`` (``compliance_officer``): a required ``certification``
       that is expired, or entirely absent for a training-mandated employee, is
       ``medium``.
    3. ``contract_missing_field`` (``hr_admin``): an active employee lacking
       ``email``/``department_id``/``job_title``/``phone`` is ``low`` per field.

    Terminated employees are excluded from document/training evaluations.
    """
    context: dict[uuid.UUID, EmployeeComplianceContext] = {
        e.employee_id: e for e in employees.values()
    }
    active_ids = {
        eid
        for eid, ctx in context.items()
        if ctx.status != "terminated"
    }

    findings: list[ComplianceFinding] = []

    # document_expiry — one finding per at-risk identity document.
    for doc in documents:
        if doc.status != "active":
            continue
        if doc.doc_type not in _COMPLIANCE_EXPIRING_DOC_TYPES:
            continue
        if doc.expiry_date is None:
            continue
        if doc.employee_id not in active_ids:
            continue
        days = _days_until(doc.expiry_date, today)
        if days < 0:
            severity, label = "high", "has expired"
        elif days <= expiry_window_days:
            severity, label = "medium", "expires soon"
        else:
            continue
        findings.append(
            ComplianceFinding(
                employee_id=doc.employee_id,
                check_type="document_expiry",
                severity=severity,
                owner_rule="compliance_officer",
                title="Identity document expiring",
                description=(
                    f"{doc.doc_type} document {label} "
                    f"({abs(days)} day(s) {'past due' if days < 0 else 'remaining'})."
                ),
                evidence={
                    "doc_type": doc.doc_type,
                    "document_id": str(doc.document_id),
                    "expiry_date": doc.expiry_date.isoformat(),
                    "days_left": days,
                },
            )
        )

    certifications_by_employee: dict[uuid.UUID, list[DocumentComplianceSignal]] = {}
    for doc in documents:
        if doc.doc_type != "certification":
            continue
        certifications_by_employee.setdefault(doc.employee_id, []).append(doc)

    # training_overdue — expired required certification, or none at all.
    for eid, ctx in context.items():
        if eid not in active_ids:
            continue
        certs = certifications_by_employee.get(eid, [])
        expired = [
            c
            for c in certs
            if c.is_required
            and c.status == "active"
            and c.expiry_date is not None
            and _days_until(c.expiry_date, today) < 0
        ]
        for cert in sorted(expired, key=lambda c: c.expiry_date or date.max):
            days_late = -_days_until(cert.expiry_date, today)  # type: ignore[arg-type]
            findings.append(
                ComplianceFinding(
                    employee_id=eid,
                    check_type="training_overdue",
                    severity="medium",
                    owner_rule="compliance_officer",
                    title="Required training overdue",
                    description=(
                        f"Required certification is {days_late} day(s) past its "
                        "expiry date."
                    ),
                    evidence={
                        "doc_type": "certification",
                        "document_id": str(cert.document_id),
                        "expiry_date": cert.expiry_date.isoformat(),
                        "days_late": days_late,
                    },
                )
            )
        if ctx.requires_training and not certs:
            findings.append(
                ComplianceFinding(
                    employee_id=eid,
                    check_type="training_overdue",
                    severity="medium",
                    owner_rule="compliance_officer",
                    title="Required training missing",
                    description="Employee has no certification document on file.",
                    evidence={"doc_type": "certification", "missing": True},
                )
            )

    # contract_missing_field — active employee with a missing HR field (low).
    field_names: tuple[str, ...] = ("email", "department_id", "job_title", "phone")
    for eid, ctx in context.items():
        if eid not in active_ids:
            continue
        missing = [
            name
            for name in field_names
            if getattr(ctx, name) is None or str(getattr(ctx, name)).strip() == ""
        ]
        for name in missing:
            findings.append(
                ComplianceFinding(
                    employee_id=eid,
                    check_type="contract_missing_field",
                    severity="low",
                    owner_rule="hr_admin",
                    title="Missing employee record field",
                    description=f"{name} is missing from the employee record.",
                    evidence={"missing_fields": [name]},
                )
            )

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(
        findings,
        key=lambda f: (
            severity_order.get(f.severity, 3),
            f.check_type,
            str(f.employee_id or ""),
        ),
    )


__all__ = [
    "AnomalyFinding",
    "ComplianceFinding",
    "DocumentComplianceSignal",
    "EmployeeComplianceContext",
    "Holiday",
    "PayrollAnomalyFinding",
    "PayrollEmployeeContext",
    "PayrollEntrySignal",
    "RequestSignal",
    "detect_compliance_findings",
    "detect_leave_pattern_anomalies",
    "detect_payroll_anomalies",
    "mask_account",
    "normalize_account",
    "ratio_severity",
]
