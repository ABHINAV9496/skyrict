"""Application-wide constants — single source of truth for magic values.

Services, schemas, and configs import from here instead of hardcoding strings.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# JWT / Token constants
# ---------------------------------------------------------------------------
ALGORITHM_RS256 = "RS256"
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------
API_V1_PREFIX = "/api/v1"
SERVICE_NAME = "identity"
SERVICE_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Problem type URIs (RFC 7807)
# ---------------------------------------------------------------------------
PROBLEM_BASE_URL = "https://api.skyrict.io/problems"

PROBLEM_TOKEN_EXPIRED = f"{PROBLEM_BASE_URL}/token-expired"
PROBLEM_TOKEN_INVALID = f"{PROBLEM_BASE_URL}/token-invalid"
PROBLEM_TOKEN_REUSE_DETECTED = f"{PROBLEM_BASE_URL}/token-reuse-detected"
PROBLEM_AUTHENTICATION_ERROR = f"{PROBLEM_BASE_URL}/authentication-error"
PROBLEM_EMAIL_NOT_VERIFIED = f"{PROBLEM_BASE_URL}/email-not-verified"
PROBLEM_AUTHORIZATION_ERROR = f"{PROBLEM_BASE_URL}/authorization-error"
PROBLEM_MFA_REQUIRED = f"{PROBLEM_BASE_URL}/mfa-required"
PROBLEM_USER_NOT_FOUND = f"{PROBLEM_BASE_URL}/user-not-found"
PROBLEM_TENANT_NOT_FOUND = f"{PROBLEM_BASE_URL}/tenant-not-found"
PROBLEM_USER_ALREADY_EXISTS = f"{PROBLEM_BASE_URL}/user-already-exists"
PROBLEM_VALIDATION_ERROR = f"{PROBLEM_BASE_URL}/validation-error"
PROBLEM_RATE_LIMIT_EXCEEDED = f"{PROBLEM_BASE_URL}/rate-limit-exceeded"
PROBLEM_TENANT_DISABLED = f"{PROBLEM_BASE_URL}/tenant-disabled"
PROBLEM_USER_DISABLED = f"{PROBLEM_BASE_URL}/user-disabled"
PROBLEM_TENANT_CONTEXT_MISSING = f"{PROBLEM_BASE_URL}/tenant-context-missing"
PROBLEM_TENANT_MISMATCH = f"{PROBLEM_BASE_URL}/tenant-mismatch"
PROBLEM_INTERNAL_ERROR = f"{PROBLEM_BASE_URL}/internal-error"

# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------
DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES = 15
DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS = 7
DEFAULT_TOKEN_EXPIRE_SECONDS = 900
DEFAULT_PAGE_SIZE = 20
DEFAULT_RATE_LIMIT_LOGIN = 5
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 300

# ---------------------------------------------------------------------------
# Login security posture (see ADR-004)
#
# One message for EVERY login failure (unknown email, wrong password,
# disabled, unverified) so the API exposes no account-existence oracle via
# status code, problem type, or detail. The frontend guides recovery via
# account-level state (SKY-21), never via backend error semantics.
# ---------------------------------------------------------------------------
LOGIN_FAILED_MESSAGE = "Invalid email or password."

# ---------------------------------------------------------------------------
# Skip-auth paths (middleware bypass)
#
# These are the REAL mounted paths (the api_router is mounted under /api/v1).
# Everything else — including /api/v1/auth/login — requires tenant resolution
# so the tenant is known before route execution. /auth/register and
# /auth/verify-email are self-service (no tenant exists yet), so they bypass
# tenant resolution.
# ---------------------------------------------------------------------------
SKIP_AUTH_PATHS = frozenset(
    {
        f"{API_V1_PREFIX}/health",
        f"{API_V1_PREFIX}/ready",
        f"{API_V1_PREFIX}/auth/register",
        f"{API_V1_PREFIX}/auth/verify-email",
        f"{API_V1_PREFIX}/invitations/accept",
        "/docs",
        "/openapi.json",
        "/redoc",
    }
)

# ---------------------------------------------------------------------------
# Default system roles (single source of truth)
#
# Provisioned for every tenant at self-service registration and seeded for the
# default tenant. Permission keys must come from the platform-fixed catalog
# seeded by the 0001 migration (``PERMISSION_CATALOG``). Kept in core so the
# auth feature (provisioning), the roles feature (validation), and seed tooling
# can all import it without crossing feature boundaries.
# ---------------------------------------------------------------------------
SYSTEM_ROLE_DEFINITIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tenant_owner", ("*", "invitations:send")),
    (
        "organization_admin",
        (
            "users:read",
            "users:write",
            "users:delete",
            "roles:read",
            "roles:write",
            "tenants:read",
            "tenants:write",
            "sessions:read",
            "sessions:revoke",
            "audit:read",
            "mfa:manage",
            "sso:manage",
            "settings:read",
            "settings:write",
            "billing.manage",
            "invitations:send",
        ),
    ),
    (
        "department_manager",
        (
            "users:read",
            "roles:read",
            "settings:read",
            "sessions:read",
            "erp.invoice.read",
            "erp.purchase.approve",
        ),
    ),
    (
        "standard_user",
        ("users:read", "settings:read", "erp.invoice.read"),
    ),
    (
        "auditor",
        ("audit:read", "sessions:read", "users:read", "roles:read"),
    ),
)

SYSTEM_ROLE_NAMES = frozenset(name for name, _ in SYSTEM_ROLE_DEFINITIONS)

INVITATION_TOKEN_EXPIRE_DAYS = 7
DEFAULT_INVITE_ROLE = "viewer"

PROBLEM_INVITATION_NOT_FOUND = f"{PROBLEM_BASE_URL}/invitation-not-found"
PROBLEM_INVITATION_EXPIRED = f"{PROBLEM_BASE_URL}/invitation-expired"
PROBLEM_INVITATION_ALREADY_USED = f"{PROBLEM_BASE_URL}/invitation-already-used"
PROBLEM_INVITATION_EMAIL_MISMATCH = f"{PROBLEM_BASE_URL}/invitation-email-mismatch"
