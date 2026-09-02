"""Unit tests for the shared leave-pattern anomaly rules (HR-AI-002 8.2.1).

These exercise the LITERAL engine that core deploys and that the ai-agent eval
harness grades (``anomaly_precision``). They mirror the core contract the
runtime tests already assert: the team-size gate, the >=3x-median magnitude
rules, and the two new pattern rules (short-notice Monday/Friday and
pre-holiday spike) with their severity bands.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import TYPE_CHECKING

from skyrict_common.ai_hr_rules import (
    ComplianceFinding,
    DocumentComplianceSignal,
    EmployeeComplianceContext,
    Holiday,
    RequestSignal,
    detect_compliance_findings,
    detect_leave_pattern_anomalies,
    ratio_severity,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

TEAM = uuid.UUID("11111111-1111-1111-1111-111111111111")
E1 = uuid.UUID("22222222-2222-2222-2222-222222222222")
E2 = uuid.UUID("33333333-3333-3333-3333-333333333333")
E3 = uuid.UUID("44444444-4444-4444-4444-444444444444")
E4 = uuid.UUID("55555555-5555-5555-5555-555555555555")
TODAY = date(2026, 8, 29)


def _req(
    days: int,
    start: date,
    *,
    filed_on: date | None = None,
    employee_id: uuid.UUID = E1,
    request_id: uuid.UUID | None = None,
) -> RequestSignal:
    return RequestSignal(
        request_id=request_id or uuid.uuid4(),
        employee_id=employee_id,
        start_date=start,
        end_date=start + timedelta(days=days - 1),
        days=days,
        leave_type="annual",
        filed_on=filed_on or start,
    )


def _run(
    members: Sequence[uuid.UUID],
    requests: dict[uuid.UUID, list[RequestSignal]],
    *,
    holidays: Sequence[Holiday] = (),
    today: date = TODAY,
) -> list:
    return detect_leave_pattern_anomalies(
        members={TEAM: list(members)},
        requests_by_employee=requests,
        holidays=holidays,
        today=today,
    )


def _found(findings, anomaly_type: str):
    return [f for f in findings if f.anomaly_type == anomaly_type]


# -- team-size gate (Gherkin: < 4 members -> abstain) -------------------------


def test_team_size_gate_abstains_for_three_members() -> None:
    requests = {E1: [_req(30, TODAY - timedelta(days=10))], E2: [], E3: []}
    assert _run([E1, E2, E3], requests) == []


def test_team_size_gate_passes_for_four_members() -> None:
    base = TODAY - timedelta(days=10)
    requests = {
        E1: [_req(30, base)],
        E2: [_req(2, base + timedelta(days=5))],
        E3: [_req(2, base + timedelta(days=6))],
        E4: [_req(2, base + timedelta(days=7))],
    }
    findings = _run([E1, E2, E3, E4], requests)
    assert len(_found(findings, "leave_overuse")) == 1


# -- magnitude rules ----------------------------------------------------------


def test_leave_overuse_fires_above_three_times_median() -> None:
    base = TODAY - timedelta(days=30)
    requests = {
        E1: [_req(20, base), _req(2, base + timedelta(days=20))],
        E2: [_req(2, base + timedelta(days=5))],
        E3: [_req(2, base + timedelta(days=6))],
        E4: [_req(2, base + timedelta(days=7))],
    }
    findings = _run([E1, E2, E3, E4], requests)
    (overuse,) = _found(findings, "leave_overuse")
    assert overuse.employee_id == E1
    assert overuse.evidence["leave_days"] == 22
    assert overuse.evidence["team_median_days"] == 2.0
    assert overuse.severity == "critical"  # 22 / 2 = 11x


def test_frequent_absence_fires_above_three_times_median_count() -> None:
    base = TODAY - timedelta(days=30)
    requests = {
        E1: [_req(1, base + timedelta(days=i)) for i in range(8)],
        E2: [_req(2, base + timedelta(days=5))],
        E3: [_req(1, base + timedelta(days=6))],
        E4: [_req(1, base + timedelta(days=7))],
    }
    findings = _run([E1, E2, E3, E4], requests)
    (frequent,) = _found(findings, "frequent_absence")
    assert frequent.employee_id == E1
    assert frequent.evidence["request_count"] == 8
    assert frequent.evidence["team_median_count"] == 1.0


def test_no_anomaly_when_below_threshold() -> None:
    base = TODAY - timedelta(days=30)
    requests = {
        E1: [_req(4, base)],
        E2: [_req(2, base + timedelta(days=5))],
        E3: [_req(2, base + timedelta(days=6))],
        E4: [_req(2, base + timedelta(days=7))],
    }
    assert _run([E1, E2, E3, E4], requests) == []


def test_ratio_severity() -> None:
    assert ratio_severity(7.0) == "critical"
    assert ratio_severity(4.0) == "high"
    assert ratio_severity(3.2) == "medium"
    assert ratio_severity(40.0) == "critical"


# -- short_notice_monday_friday (Gherkin: Mon/Fri span, few days' notice) -----


def _short_notice_team_requests() -> dict[uuid.UUID, list[RequestSignal]]:
    base = TODAY - timedelta(days=20)
    friday = date(2026, 8, 14)  # a Friday inside the trailing window
    start = friday - timedelta(days=4)  # the Monday prior (2026-08-10)
    return {
        E1: [_req(5, start, filed_on=start - timedelta(days=4))],
        E2: [_req(1, base + timedelta(days=1))],
        E3: [_req(1, base + timedelta(days=2))],
        E4: [_req(1, base + timedelta(days=3))],
    }


def test_short_notice_monday_friday_fires() -> None:
    findings = _run([E1, E2, E3, E4], _short_notice_team_requests())
    (fired,) = _found(findings, "short_notice_monday_friday")
    assert fired.employee_id == E1
    assert fired.evidence["advance_days"] == 4
    assert fired.severity == "medium"  # > 3 day pressing threshold


def test_short_notice_pressing_is_high() -> None:
    requests = _short_notice_team_requests()
    rq = requests[E1][0]
    requests[E1] = [
        RequestSignal(
            request_id=rq.request_id,
            employee_id=rq.employee_id,
            start_date=rq.start_date,
            end_date=rq.end_date,
            days=rq.days,
            leave_type=rq.leave_type,
            filed_on=rq.start_date - timedelta(days=2),
        )
    ]
    findings = _run([E1, E2, E3, E4], requests)
    (fired,) = _found(findings, "short_notice_monday_friday")
    assert fired.evidence["advance_days"] == 2
    assert fired.severity == "high"


def test_short_notice_needs_a_long_block() -> None:
    requests = _short_notice_team_requests()
    rq = requests[E1][0]
    requests[E1] = [
        RequestSignal(
            request_id=rq.request_id,
            employee_id=rq.employee_id,
            start_date=rq.start_date,
            end_date=rq.start_date,
            days=1,
            leave_type=rq.leave_type,
            filed_on=rq.start_date - timedelta(days=4),
        )
    ]
    assert _found(_run([E1, E2, E3, E4], requests), "short_notice_monday_friday") == []


# -- pre_holiday_spike (Gherkin: span near a public holiday, > 3x median) -----


def _holiday_team_requests(block_start: date) -> dict[uuid.UUID, list[RequestSignal]]:
    base = TODAY - timedelta(days=20)
    return {
        E1: [_req(7, block_start)],
        E2: [_req(2, base)],
        E3: [_req(2, base + timedelta(days=1))],
        E4: [_req(2, base + timedelta(days=2))],
    }


def test_pre_holiday_spike_fires_within_adjacency() -> None:
    holiday = date(2026, 8, 11)  # remains inside the trailing window
    requests = _holiday_team_requests(date(2026, 8, 4))  # 08-04 .. 08-10
    holidays = [Holiday(holiday, "Test Day", None)]
    findings = _run([E1, E2, E3, E4], requests, holidays=holidays)
    (fired,) = _found(findings, "pre_holiday_spike")
    assert fired.employee_id == E1
    assert fired.evidence["holiday_name"] == "Test Day"
    assert fired.evidence["distance_days"] == 1  # span ends the day before holiday
    assert fired.severity == "medium"


def test_pre_holiday_spike_absent_when_far_from_holiday() -> None:
    holiday = date(2026, 8, 1)
    requests = _holiday_team_requests(date(2026, 8, 4))  # 08-04 .. 08-10
    findings = _run([E1, E2, E3, E4], requests, holidays=[Holiday(holiday, "Far", None)])
    assert _found(findings, "pre_holiday_spike") == []


def test_pre_holiday_spike_scoped_to_own_department() -> None:
    holiday = date(2026, 8, 11)
    other_dept = uuid.uuid4()
    requests = _holiday_team_requests(date(2026, 8, 4))
    findings = _run(
        [E1, E2, E3, E4],
        requests,
        holidays=[Holiday(holiday, "Other Dept Only", other_dept)],
    )
    assert _found(findings, "pre_holiday_spike") == []


def test_pre_holiday_spike_overlap_is_high() -> None:
    holiday = date(2026, 8, 11)
    requests = _holiday_team_requests(date(2026, 8, 8))  # 08-08 .. 08-14 covers 08-11
    findings = _run([E1, E2, E3, E4], requests, holidays=[Holiday(holiday, "Overlap", None)])
    (fired,) = _found(findings, "pre_holiday_spike")
    assert fired.evidence["distance_days"] == 0
    assert fired.severity == "high"


# ---------------------------------------------------------------------------
# Payroll anomaly rules (HR-AI-001, Unit B) — the LITERAL engine core deploys.
# ---------------------------------------------------------------------------

from skyrict_common.ai_hr_rules import (  # noqa: E402
    PayrollAnomalyFinding,
    PayrollEmployeeContext,
    PayrollEntrySignal,
    detect_payroll_anomalies,
    mask_account,
    normalize_account,
)


def _entry(
    emp_id: uuid.UUID,
    run_code: str,
    net: float,
    *,
    pay_days: int = 22,
    period_end: date = TODAY,
) -> PayrollEntrySignal:
    return PayrollEntrySignal(
        employee_id=emp_id,
        run_code=run_code,
        period_start=period_end - timedelta(days=pay_days),
        period_end=period_end,
        base_salary=0.0,
        pay_days=pay_days,
        gross=0.0,
        deductions=0.0,
        net=net,
    )


def _ctx(emp_id: uuid.UUID, **overrides) -> PayrollEmployeeContext:
    base: dict = {"employee_id": emp_id, "status": "active", "bank_account": "GB29 NWBK 6016 1331 9268 19"}
    base.update(overrides)
    return PayrollEmployeeContext(**base)


def _run_payroll(latest: list, prior: list, *, employees: dict, delta_ratio: float = 1.5) -> list[PayrollAnomalyFinding]:
    return detect_payroll_anomalies(
        latest_entries=latest,
        prior_entries=prior,
        employees=employees,
        delta_ratio=delta_ratio,
    )


def test_payroll_flat_seed_yields_no_findings() -> None:
    """The DEMO seed pays every eligible employee flat 0.85x — nothing fires."""
    employees = {
        E1: _ctx(E1, status="active", bank_account="ACC-0001"),
        E2: _ctx(E2, status="active", bank_account="ACC-0002"),
    }
    latest = [_entry(E1, "PR-2026-04", 5100.0), _entry(E2, "PR-2026-04", 8500.0)]
    prior = [_entry(E1, "PR-2026-03", 5100.0), _entry(E2, "PR-2026-03", 8500.0)]
    assert _run_payroll(latest, prior, employees=employees) == []


def test_net_pay_delta_fires_on_spike_via_ratio_severity() -> None:
    """~2.5x net-per-day swing vs the preceding run -> medium (>= 1.5x)."""
    employees = {E1: _ctx(E1)}
    latest = [_entry(E1, "PR-2026-04", 12_750.0)]
    prior = [_entry(E1, "PR-2026-03", 5100.0)]
    (fired,) = _run_payroll(latest, prior, employees=employees)
    assert fired.anomaly_type == "net_pay_delta"
    assert fired.severity == "medium"
    assert fired.employee_id == E1
    assert fired.evidence["ratio"] == round(12_750.0 / 5100.0, 3)
    assert fired.evidence["direction"] == "increase"
    assert fired.evidence["current_run"] == "PR-2026-04"


def test_net_pay_delta_uses_pay_days_normalization() -> None:
    """A swing in PAY DAYS, not pay, with a flat daily rate must NOT fire."""
    employees = {E1: _ctx(E1)}
    latest = [_entry(E1, "PR-2026-04", 5100.0, pay_days=22)]
    prior = [_entry(E1, "PR-2026-03", 3400.0, pay_days=14)]
    assert _run_payroll(latest, prior, employees=employees) == []


def test_net_pay_delta_absents_without_prior_entry() -> None:
    employees = {E1: _ctx(E1)}
    latest = [_entry(E1, "PR-2026-04", 12_750.0)]
    assert _run_payroll(latest, prior=[], employees=employees) == []


def test_duplicate_account_shares_medium_for_two() -> None:
    employees = {
        E1: _ctx(E1, bank_account="GB29 NWBK 6016 1331 9268 19"),
        E2: _ctx(E2, bank_account="gb29nwbk60161331926819"),  # same, normalized
    }
    latest = [_entry(E1, "PR-2026-04", 5100.0), _entry(E2, "PR-2026-04", 8500.0)]
    (fired,) = _found(_run_payroll(latest, [], employees=employees), "duplicate_account")
    assert fired.severity == "medium"
    assert set(fired.evidence["employee_ids"]) == {str(E1), str(E2)}
    assert fired.employee_id == E2  # highest net is the primary subject
    assert fired.evidence["account_masked"] == "****6819"
    assert "gb29nwbk60161331926819" not in str(fired.evidence)


def test_duplicate_account_matches_normalized_keys() -> None:
    employees = {
        E1: _ctx(E1, bank_account="GB29 NWBK 6016 1331 9268 19"),
        E3: _ctx(E3, bank_account="GB29-NWBK-6016-1331-9268-19"),
    }
    latest = [_entry(E1, "PR-2026-04", 5100.0), _entry(E3, "PR-2026-04", 5100.0)]
    (fired,) = _found(_run_payroll(latest, [], employees=employees), "duplicate_account")
    assert fired.severity == "medium"
    assert fired.evidence["employee_count"] == 2


def test_duplicate_account_three_is_high_and_terminated_is_critical() -> None:
    employees = {
        E1: _ctx(E1, bank_account="ACC-1234"),
        E2: _ctx(E2, bank_account="ACC-1234"),
        E3: _ctx(E3, bank_account="ACC-1234"),
    }
    latest = [
        _entry(E1, "PR-2026-04", 5100.0),
        _entry(E2, "PR-2026-04", 5100.0),
        _entry(E3, "PR-2026-04", 5100.0),
    ]
    (fired,) = _found(_run_payroll(latest, [], employees=employees), "duplicate_account")
    assert fired.severity == "high"

    terminated = {E1: _ctx(E1, status="terminated", bank_account="ACC-1234"), E2: _ctx(E2, bank_account="ACC-1234")}
    pair = [_entry(E1, "PR-2026-04", 5100.0), _entry(E2, "PR-2026-04", 5100.0)]
    (critical,) = _found(_run_payroll(pair, [], employees=terminated), "duplicate_account")
    assert critical.severity == "critical"
    assert critical.evidence["includes_terminated"] is True


def test_ghost_employee_paid_while_terminated_is_critical() -> None:
    employees = {E1: _ctx(E1, status="terminated", termination_date=date(2026, 7, 15))}
    latest = [_entry(E1, "PR-2026-04", 5100.0)]
    (fired,) = _found(_run_payroll(latest, [], employees=employees), "ghost_employee")
    assert fired.severity == "critical"
    assert fired.evidence["termination_date"] == "2026-07-15"


def test_ghost_employee_no_bank_account_is_medium() -> None:
    employees = {E1: _ctx(E1, bank_account=None)}
    latest = [_entry(E1, "PR-2026-04", 5100.0)]
    (fired,) = _found(_run_payroll(latest, [], employees=employees), "ghost_employee")
    assert fired.severity == "medium"
    assert fired.evidence["has_bank_account"] is False


def test_ghost_employee_active_with_account_silent() -> None:
    employees = {E1: _ctx(E1)}
    latest = [_entry(E1, "PR-2026-04", 5100.0)]
    assert _run_payroll(latest, [], employees=employees) == []


def test_findings_sorted_critical_first_then_type() -> None:
    employees = {
        E1: _ctx(E1, status="terminated", termination_date=date(2026, 6, 1)),
        E2: _ctx(E2, bank_account="A1"),
        E3: _ctx(E3, bank_account="A2"),
        E4: _ctx(E4),
    }
    latest = [
        _entry(E1, "PR-2026-04", 5100.0),
        _entry(E2, "PR-2026-04", 5100.0),
        _entry(E3, "PR-2026-04", 5100.0),
    ]
    findings = _run_payroll(latest, [], employees=employees)
    assert findings[0].severity == "critical"
    assert findings[0].anomaly_type == "ghost_employee"
    assert findings[-1].anomaly_type == "ghost_employee"
    severities = [f.severity for f in findings]
    assert severities == sorted(severities, key=lambda s: _SEVERITY_ORDER[s])


_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def test_mask_account_last_four_only() -> None:
    assert mask_account("GB29 NWBK 6016 1331 9268 19") == "****6819"
    assert mask_account("1234") == "****"
    assert mask_account("  1234  ") == "****"


def test_normalize_account_is_case_and_punctuation_insensitive() -> None:
    assert normalize_account("GB29 NWBK 6016 1331 9268 19") == "gb29nwbk60161331926819"
    assert normalize_account("gb29-nwbk-6016-1331-9268-19") == "gb29nwbk60161331926819"


# -- compliance rule pack v1 (HR-AI-001, Unit C) ------------------------------


def _compliance_ctx(
    eid: uuid.UUID,
    *,
    status: str = "active",
    email: str = "e@acme.test",
    department_id: uuid.UUID | None = TEAM,
    job_title: str = "Engineer",
    phone: str = "555-0100",
    requires_training: bool = False,
) -> EmployeeComplianceContext:
    return EmployeeComplianceContext(
        employee_id=eid,
        status=status,
        email=email,
        department_id=department_id,
        job_title=job_title,
        phone=phone,
        requires_training=requires_training,
    )


def _run_compliance(
    documents: Sequence[DocumentComplianceSignal],
    *,
    employees: dict[uuid.UUID, EmployeeComplianceContext],
    today: date = TODAY,
) -> list[ComplianceFinding]:
    return detect_compliance_findings(
        documents=documents,
        employees=employees,
        today=today,
    )


def _c_found(findings, check_type: str):
    return [f for f in findings if f.check_type == check_type]


def test_compliance_clean_seed_is_quiet() -> None:
    """Clean active employees with complete fields and valid docs fire nothing."""
    employees = {E1: _compliance_ctx(E1), E2: _compliance_ctx(E2)}
    docs = [
        DocumentComplianceSignal(
            employee_id=E1, document_id=uuid.uuid4(), doc_type="work_permit",
            expiry_date=TODAY + timedelta(days=90), is_required=True,
        )
    ]
    assert _run_compliance(docs, employees=employees) == []


def test_document_expiry_past_is_high() -> None:
    employees = {E1: _compliance_ctx(E1)}
    docs = [
        DocumentComplianceSignal(
            employee_id=E1, document_id=uuid.uuid4(), doc_type="visa",
            expiry_date=TODAY - timedelta(days=5), is_required=True,
        )
    ]
    (fired,) = _run_compliance(docs, employees=employees)
    assert fired.check_type == "document_expiry"
    assert fired.severity == "high"
    assert fired.owner_rule == "compliance_officer"
    assert fired.evidence["days_left"] == -5
    assert fired.evidence["expiry_date"] == (TODAY - timedelta(days=5)).isoformat()


def test_document_expiry_soon_is_medium() -> None:
    employees = {E1: _compliance_ctx(E1)}
    docs = [
        DocumentComplianceSignal(
            employee_id=E1, document_id=uuid.uuid4(), doc_type="passport",
            expiry_date=TODAY + timedelta(days=20), is_required=True,
        )
    ]
    (fired,) = _run_compliance(docs, employees=employees)
    assert fired.severity == "medium"
    assert fired.evidence["days_left"] == 20
    assert fired.evidence["doc_type"] == "passport"


def test_document_expiry_outside_window_is_silent() -> None:
    employees = {E1: _compliance_ctx(E1)}
    docs = [
        DocumentComplianceSignal(
            employee_id=E1, document_id=uuid.uuid4(), doc_type="national_id",
            expiry_date=TODAY + timedelta(days=90), is_required=True,
        )
    ]
    assert _run_compliance(docs, employees=employees) == []


def test_document_expiry_ignores_terminated_employee() -> None:
    employees = {E1: _compliance_ctx(E1, status="terminated")}
    docs = [
        DocumentComplianceSignal(
            employee_id=E1, document_id=uuid.uuid4(), doc_type="visa",
            expiry_date=TODAY - timedelta(days=2), is_required=True,
        )
    ]
    assert _run_compliance(docs, employees=employees) == []


def test_document_expiry_ignores_non_identity_document() -> None:
    employees = {E1: _compliance_ctx(E1)}
    docs = [
        DocumentComplianceSignal(
            employee_id=E1, document_id=uuid.uuid4(), doc_type="medical",
            expiry_date=TODAY - timedelta(days=2), is_required=True,
        )
    ]
    assert _run_compliance(docs, employees=employees) == []


def test_training_overdue_expired_required_certification() -> None:
    employees = {E1: _compliance_ctx(E1)}
    docs = [
        DocumentComplianceSignal(
            employee_id=E1, document_id=uuid.uuid4(), doc_type="certification",
            expiry_date=TODAY - timedelta(days=14), is_required=True,
        )
    ]
    (fired,) = _run_compliance(docs, employees=employees)
    assert fired.check_type == "training_overdue"
    assert fired.severity == "medium"
    assert fired.evidence["days_late"] == 14
    assert fired.owner_rule == "compliance_officer"


def test_training_overdue_optional_certification_is_silent() -> None:
    employees = {E1: _compliance_ctx(E1)}
    docs = [
        DocumentComplianceSignal(
            employee_id=E1, document_id=uuid.uuid4(), doc_type="certification",
            expiry_date=TODAY - timedelta(days=14), is_required=False,
        )
    ]
    assert _run_compliance(docs, employees=employees) == []


def test_training_overdue_missing_required_training() -> None:
    employees = {E1: _compliance_ctx(E1, requires_training=True)}
    (fired,) = _run_compliance([], employees=employees)
    assert fired.check_type == "training_overdue"
    assert fired.severity == "medium"
    assert fired.evidence.get("missing") is True


def test_training_overdue_not_absent_without_requirement() -> None:
    employees = {E1: _compliance_ctx(E1, requires_training=False)}
    assert _run_compliance([], employees=employees) == []


def test_contract_missing_field_fires_low_per_missing_field() -> None:
    employees = {
        E1: _compliance_ctx(E1, email=None, phone=None),
    }
    fired = _c_found(_run_compliance([], employees=employees), "contract_missing_field")
    field_names = {f.evidence["missing_fields"][0] for f in fired}
    assert field_names == {"email", "phone"}
    assert all(f.severity == "low" for f in fired)
    assert all(f.owner_rule == "hr_admin" for f in fired)
    # No employee email/phone VALUE leaks into evidence.
    raw = str(fired[0].evidence)
    assert "e@acme.test" not in raw
    assert "555-0100" not in raw


def test_contract_missing_field_ignores_terminated() -> None:
    employees = {E1: _compliance_ctx(E1, status="terminated", email=None)}
    assert _run_compliance([], employees=employees) == []


def test_compliance_no_pii_in_evidence() -> None:
    employees = {
        E1: _compliance_ctx(E1, email="alice@corp.test", phone="555-1234"),
    }
    docs = [
        DocumentComplianceSignal(
            employee_id=E1, document_id=uuid.uuid4(), doc_type="visa",
            expiry_date=TODAY - timedelta(days=1), is_required=True,
        )
    ]
    for f in _run_compliance(docs, employees=employees):
        serialized = str(f.evidence)
        assert "alice@corp.test" not in serialized
        assert "555-1234" not in serialized
        assert "Engineer" not in serialized
