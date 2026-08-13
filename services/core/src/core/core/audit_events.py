"""Canonical audit event keys for the core (ERP) domain.

Single source of truth for the free-form ``action`` strings written to
``core_audit_logs``. Services must reference these constants instead of
hardcoding strings so the event vocabulary stays greppable and drift-checked
against the catalog grouping below.

Vocabulary is defined by the HR & Payroll design doc (``docs/modules/
hr-payroll.md``, step 4) — ``{domain}.{entity}.{action}``, e.g. ``hr.leave
.approved``.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# HR
# ---------------------------------------------------------------------------
HR_DEPARTMENT_CREATED = "hr.department.created"
HR_DEPARTMENT_UPDATED = "hr.department.updated"
HR_EMPLOYEE_CREATED = "hr.employee.created"
HR_EMPLOYEE_UPDATED = "hr.employee.updated"
HR_EMPLOYEE_TERMINATED = "hr.employee.terminated"
HR_LEAVE_REQUESTED = "hr.leave.requested"
HR_LEAVE_APPROVED = "hr.leave.approved"
HR_LEAVE_REJECTED = "hr.leave.rejected"
HR_LEAVE_CANCELLED = "hr.leave.cancelled"
HR_LEAVE_BALANCE_ADJUSTED = "hr.leave.balance.adjusted"
HR_LEAVE_ACCRUED = "hr.leave.accrued"

# ---------------------------------------------------------------------------
# Payroll
# ---------------------------------------------------------------------------
PAYROLL_RUN_CREATED = "payroll.run.created"
PAYROLL_RUN_COMPUTED = "payroll.run.computed"
PAYROLL_RUN_APPROVED = "payroll.run.approved"
PAYROLL_RUN_PAID = "payroll.run.paid"
PAYROLL_RUN_VOIDED = "payroll.run.voided"
PAYROLL_ENTRY_ADJUSTED = "payroll.entry.adjusted"
PAYROLL_SETTINGS_UPDATED = "payroll.settings.updated"

# Every catalogued audit event, in catalog order.
CATALOG: tuple[str, ...] = (
    HR_DEPARTMENT_CREATED,
    HR_DEPARTMENT_UPDATED,
    HR_EMPLOYEE_CREATED,
    HR_EMPLOYEE_UPDATED,
    HR_EMPLOYEE_TERMINATED,
    HR_LEAVE_REQUESTED,
    HR_LEAVE_APPROVED,
    HR_LEAVE_REJECTED,
    HR_LEAVE_CANCELLED,
    HR_LEAVE_BALANCE_ADJUSTED,
    HR_LEAVE_ACCRUED,
    PAYROLL_RUN_CREATED,
    PAYROLL_RUN_COMPUTED,
    PAYROLL_RUN_APPROVED,
    PAYROLL_RUN_PAID,
    PAYROLL_RUN_VOIDED,
    PAYROLL_ENTRY_ADJUSTED,
    PAYROLL_SETTINGS_UPDATED,
)

ALL_AUDIT_EVENTS: frozenset[str] = frozenset(CATALOG)

# Event module groupings (for catalog endpoints and UI).
# Each entry: (module_key, module_label, (event_keys, ...))
AUDIT_EVENT_MODULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "hr",
        "HR",
        (
            HR_DEPARTMENT_CREATED,
            HR_DEPARTMENT_UPDATED,
            HR_EMPLOYEE_CREATED,
            HR_EMPLOYEE_UPDATED,
            HR_EMPLOYEE_TERMINATED,
            HR_LEAVE_REQUESTED,
            HR_LEAVE_APPROVED,
            HR_LEAVE_REJECTED,
            HR_LEAVE_CANCELLED,
            HR_LEAVE_BALANCE_ADJUSTED,
            HR_LEAVE_ACCRUED,
        ),
    ),
    (
        "payroll",
        "Payroll",
        (
            PAYROLL_RUN_CREATED,
            PAYROLL_RUN_COMPUTED,
            PAYROLL_RUN_APPROVED,
            PAYROLL_RUN_PAID,
            PAYROLL_RUN_VOIDED,
            PAYROLL_ENTRY_ADJUSTED,
            PAYROLL_SETTINGS_UPDATED,
        ),
    ),
)


def _assert_catalog_union() -> None:
    """Ensure AUDIT_EVENT_MODULES and CATALOG stay in sync (fail-fast on drift)."""
    module_keys = {key for _, _, keys in AUDIT_EVENT_MODULES for key in keys}
    if module_keys != ALL_AUDIT_EVENTS:
        missing = ALL_AUDIT_EVENTS - module_keys
        orphaned = module_keys - ALL_AUDIT_EVENTS
        msg = "AUDIT_EVENT_MODULES <-> CATALOG mismatch:\n"
        if missing:
            msg += f"  Missing from AUDIT_EVENT_MODULES: {sorted(missing)}\n"
        if orphaned:
            msg += f"  Orphaned in AUDIT_EVENT_MODULES: {sorted(orphaned)}\n"
        raise ValueError(msg)


_assert_catalog_union()

__all__ = [
    "ALL_AUDIT_EVENTS",
    "AUDIT_EVENT_MODULES",
    "CATALOG",
    "HR_DEPARTMENT_CREATED",
    "HR_DEPARTMENT_UPDATED",
    "HR_EMPLOYEE_CREATED",
    "HR_EMPLOYEE_UPDATED",
    "HR_EMPLOYEE_TERMINATED",
    "HR_LEAVE_ACCRUED",
    "HR_LEAVE_APPROVED",
    "HR_LEAVE_BALANCE_ADJUSTED",
    "HR_LEAVE_CANCELLED",
    "HR_LEAVE_REJECTED",
    "HR_LEAVE_REQUESTED",
    "PAYROLL_ENTRY_ADJUSTED",
    "PAYROLL_RUN_APPROVED",
    "PAYROLL_RUN_COMPUTED",
    "PAYROLL_RUN_CREATED",
    "PAYROLL_RUN_PAID",
    "PAYROLL_RUN_VOIDED",
    "PAYROLL_SETTINGS_UPDATED",
]
