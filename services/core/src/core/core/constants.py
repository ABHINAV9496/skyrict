"""Application-wide constants — single source of truth for magic values."""

from __future__ import annotations

import enum

# ---------------------------------------------------------------------------
# HR & Payroll domain enums
#
# The ORM models define their own native StrEnums (backing the Postgres enum
# types created by migration 0005). These domain copies are the values the
# service layer reasons about — identical string values, so repository mapping
# between entity.status (here) and model.status (models) is value-safe. Shared
# via constants.py per the HR/Payroll spec §2.1 ("enums, problem URIs,
# defaults").
# ---------------------------------------------------------------------------


class EmploymentStatus(enum.StrEnum):
    """Employment lifecycle — mirrors ``erp_employment_status``."""

    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    TERMINATED = "terminated"


class LeaveRequestStatus(enum.StrEnum):
    """Leave request lifecycle — mirrors ``erp_leave_request_status``."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class PayrollRunStatus(enum.StrEnum):
    """Payroll run lifecycle — mirrors ``erp_payroll_run_status``."""

    DRAFT = "draft"
    COMPUTED = "computed"
    APPROVED = "approved"
    PAID = "paid"
    VOID = "void"


class PayrollRounding(enum.StrEnum):
    """Net rounding mode — mirrors ``erp_payroll_rounding``."""

    NEAREST = "nearest"
    UP = "up"
    DOWN = "down"


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
PROBLEM_VALIDATION_ERROR = f"{PROBLEM_BASE_URL}/validation-error"
PROBLEM_INTERNAL_ERROR = f"{PROBLEM_BASE_URL}/internal-error"

# ---------------------------------------------------------------------------
# Skip-auth paths (middleware bypass) — real mounted paths under /api/v1.
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
