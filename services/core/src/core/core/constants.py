"""Application-wide constants - single source of truth for magic values."""

from __future__ import annotations

import enum

# ---------------------------------------------------------------------------
# HR & Payroll domain enums
#
# The ORM models define their own native StrEnums (backing the Postgres enum
# types created by migration 0005). These domain copies are the values the
# service layer reasons about - identical string values, so repository mapping
# between entity.status (here) and model.status (models) is value-safe. Shared
# via constants.py per the HR/Payroll spec §2.1 ("enums, problem URIs,
# defaults").
# ---------------------------------------------------------------------------


class EmploymentStatus(enum.StrEnum):
    """Employment lifecycle - mirrors ``erp_employment_status``."""

    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    TERMINATED = "terminated"


class LeaveRequestStatus(enum.StrEnum):
    """Leave request lifecycle - mirrors ``erp_leave_request_status``."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class PayrollRunStatus(enum.StrEnum):
    """Payroll run lifecycle - mirrors ``erp_payroll_run_status``."""

    DRAFT = "draft"
    COMPUTED = "computed"
    APPROVED = "approved"
    PAID = "paid"
    VOID = "void"


class PayrollJeBridgeStatus(enum.StrEnum):
    """Payroll→Finance accrual journal-entry bridge state (HR-AUT-001, Commit 4).

    Mirrors ``erp_payroll_runs.je_bridge_status`` (a String column + CHECK, not
    a native enum, so FIN-AI-001 can extend it without a migration).

    ``none``
        The bridge never ran or has nothing to book (bridge disabled on the
        tenant, run not paid, zero-dollar run, or run voided).
    ``pending``
        The run is paid but no accrual JE was created — the tenant's chart of
        accounts is missing one of the payroll account codes (5010/2010/2020),
        i.e. the same per-tenant chart gap flagged in the finance backlog
        (docs/backlog/finance-chart-of-accounts-gap.md). Queryable and
        retryable: provision the chart, then re-run the bridge.
    ``draft``
        A DRAFT accrual journal entry (source='payroll', source_ref=run id) now
        sits in the Finance inbox; it is posted/voided through the existing
        finance endpoints (FIN-AI-001 consumes this seam later).
    """

    NONE = "none"
    PENDING = "pending"
    DRAFT = "draft"


class PayrollRounding(enum.StrEnum):
    """Net rounding mode - mirrors ``erp_payroll_rounding``."""

    NEAREST = "nearest"
    UP = "up"
    DOWN = "down"


class AttendanceStatus(enum.StrEnum):
    """Daily attendance outcome - mirrors ``erp_attendance_status``."""

    ON_TIME = "on_time"
    LATE = "late"
    ABSENT = "absent"


class PayImpact(enum.StrEnum):
    """Payroll impact derived from attendance status.

    ``on_time`` -> full pay, ``late`` -> half pay, ``absent`` -> no pay for
    the day. Derived by the service, stored on the row.
    """

    FULL = "full"
    HALF = "half"
    NONE = "none"


# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------
API_V1_PREFIX = "/api/v1"
SERVICE_NAME = "core"
SERVICE_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# JWT constants
# ---------------------------------------------------------------------------
ALGORITHM_RS256 = "RS256"
TOKEN_TYPE_ACCESS = "access"

# ---------------------------------------------------------------------------
# Problem type URIs (RFC 7807)
# ---------------------------------------------------------------------------
PROBLEM_BASE_URL = "https://api.skyrict.io/problems"

PROBLEM_TOKEN_INVALID = f"{PROBLEM_BASE_URL}/token-invalid"
PROBLEM_TOKEN_EXPIRED = f"{PROBLEM_BASE_URL}/token-expired"
PROBLEM_AUTHENTICATION_ERROR = f"{PROBLEM_BASE_URL}/authentication-error"
PROBLEM_TENANT_CONTEXT_MISSING = f"{PROBLEM_BASE_URL}/tenant-context-missing"
PROBLEM_TENANT_MISMATCH = f"{PROBLEM_BASE_URL}/tenant-mismatch"
PROBLEM_TENANT_NOT_FOUND = f"{PROBLEM_BASE_URL}/tenant-not-found"
PROBLEM_TENANT_DISABLED = f"{PROBLEM_BASE_URL}/tenant-disabled"
PROBLEM_PERMISSION_DENIED = f"{PROBLEM_BASE_URL}/permission-denied"
PROBLEM_NOT_FOUND = f"{PROBLEM_BASE_URL}/not-found"
PROBLEM_CONFLICT = f"{PROBLEM_BASE_URL}/conflict"
PROBLEM_VALIDATION_ERROR = f"{PROBLEM_BASE_URL}/validation-error"
PROBLEM_INTERNAL_ERROR = f"{PROBLEM_BASE_URL}/internal-error"

# ---------------------------------------------------------------------------
# Finance - document numbering
# ---------------------------------------------------------------------------
INVOICE_PREFIX = "INV"
PAYMENT_PREFIX = "PMT"

# ---------------------------------------------------------------------------
# Finance - standard account codes for auto-generated entries.
# Fixed platform defaults (user-editable COA entries still override at runtime).
# ---------------------------------------------------------------------------
AR_ACCOUNT_CODE = "1100"
CASH_ACCOUNT_CODE = "1200"
AP_ACCOUNT_CODE = "2110"
REVENUE_ACCOUNT_CODE = "4000"
COGS_ACCOUNT_CODE = "5000"
INVENTORY_ASSET_ACCOUNT_CODE = "1300"
# Payroll accrual codes (HR-AUT-001, Commit 4) — reuse the demo chart's codes,
# seeded per-tenant by the finance owner (see backlog gap doc). The bridge
# books DR Salaries Expense / CR Accrued Salaries / CR Deductions Payable.
SALARY_EXPENSE_ACCOUNT_CODE = "5010"
ACCRUED_SALARIES_PAYABLE_ACCOUNT_CODE = "2010"
DEDUCTIONS_PAYABLE_ACCOUNT_CODE = "2020"

# ---------------------------------------------------------------------------
# Finance - journal entry and invoice provenance (idempotency source keys).
# ---------------------------------------------------------------------------
JOURNAL_SOURCE_MANUAL = "manual"
JOURNAL_SOURCE_INVOICE = "invoice"
JOURNAL_SOURCE_PAYMENT = "payment"
JOURNAL_SOURCE_COGS = "cogs"
JOURNAL_SOURCE_PAYROLL = "payroll"
INVOICE_SOURCE_MANUAL = "manual"
INVOICE_SOURCE_SALES_ORDER = "sales_order"
PAYMENT_SOURCE_MANUAL = "manual"

# ---------------------------------------------------------------------------
# Skip-auth paths (middleware bypass) - real mounted paths under /api/v1.
# ---------------------------------------------------------------------------
SKIP_AUTH_PATHS = frozenset(
    {
        f"{API_V1_PREFIX}/health",
        f"{API_V1_PREFIX}/ready",
        "/docs",
        "/openapi.json",
        "/redoc",
    }
)

# ---------------------------------------------------------------------------
# Multi-tenancy
# ---------------------------------------------------------------------------
# Platform-owned slugs never resolve to a tenant (mirrors identity). The
# routing contract is identical: Host subdomain in staging/production,
# X-Tenant-Slug header injected by nginx in dev/test.
RESERVED_SLUGS = frozenset(
    {
        "admin",
        "api",
        "app",
        "blog",
        "docs",
        "dev",
        "help",
        "mail",
        "signin",
        "signup",
        "staging",
        "status",
        "support",
        "test",
        "web",
        "www",
        "acme",
        "skyrict",
    }
)
