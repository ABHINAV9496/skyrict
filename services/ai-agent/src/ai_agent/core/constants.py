"""Application-wide constants - single source of truth for magic values."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------
API_V1_PREFIX = "/api/v1"
SERVICE_NAME = "ai-agent"
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

# AI-specific problem types (SKY-57 error contract). The frontend mock-fallback
# policy keys off ``ai_unavailable`` - keep the string stable.
PROBLEM_AI_UNAVAILABLE = f"{PROBLEM_BASE_URL}/ai-unavailable"
PROBLEM_AI_INVALID_RESPONSE = f"{PROBLEM_BASE_URL}/ai-invalid-response"
PROBLEM_AI_RATE_LIMITED = f"{PROBLEM_BASE_URL}/ai-rate-limited"
PROBLEM_AI_DATA_RESIDENCY = f"{PROBLEM_BASE_URL}/ai-data-residency"

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
# Platform-owned slugs never resolve to a tenant (mirrors core/identity). The
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
