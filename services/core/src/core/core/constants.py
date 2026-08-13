"""Application-wide constants — single source of truth for magic values."""

from __future__ import annotations

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
# Finance — document numbering
# ---------------------------------------------------------------------------
INVOICE_PREFIX = "INV"
PAYMENT_PREFIX = "PMT"

# ---------------------------------------------------------------------------
# Finance — standard account codes for auto-generated entries.
# Fixed platform defaults (user-editable COA entries still override at runtime).
# ---------------------------------------------------------------------------
AR_ACCOUNT_CODE = "1100"
CASH_ACCOUNT_CODE = "1200"
AP_ACCOUNT_CODE = "2110"
REVENUE_ACCOUNT_CODE = "4000"

# ---------------------------------------------------------------------------
# Finance — journal entry and invoice provenance (idempotency source keys).
# ---------------------------------------------------------------------------
JOURNAL_SOURCE_MANUAL = "manual"
JOURNAL_SOURCE_INVOICE = "invoice"
JOURNAL_SOURCE_PAYMENT = "payment"
INVOICE_SOURCE_MANUAL = "manual"
INVOICE_SOURCE_SALES_ORDER = "sales_order"
PAYMENT_SOURCE_MANUAL = "manual"

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
