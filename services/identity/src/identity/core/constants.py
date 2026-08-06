"""
Application-wide constants â€” single source of truth for magic values.

Services, schemas, and configs import from here instead of hardcoding strings.
"""

from __future__ import annotations

ALGORITHM_RS256 = "RS256"
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


API_V1_PREFIX = "/api/v1"
SERVICE_NAME = "identity"
SERVICE_VERSION = "0.1.0"


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


DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES = 15
DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS = 7
DEFAULT_TOKEN_EXPIRE_SECONDS = 900
DEFAULT_PAGE_SIZE = 20
DEFAULT_RATE_LIMIT_LOGIN = 5
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 300


LOGIN_FAILED_MESSAGE = "Invalid email or password."


SKIP_AUTH_PATHS = frozenset(
    {
        f"{API_V1_PREFIX}/health",
        f"{API_V1_PREFIX}/ready",
        f"{API_V1_PREFIX}/auth/signup/start",
        f"{API_V1_PREFIX}/auth/signup/send-code",
        f"{API_V1_PREFIX}/auth/signup/verify-code",
        f"{API_V1_PREFIX}/auth/signup/password",
        f"{API_V1_PREFIX}/auth/signup/check-email",
        f"{API_V1_PREFIX}/auth/signup/check-slug",
        f"{API_V1_PREFIX}/auth/signup/organization",
        f"{API_V1_PREFIX}/invitations/accept",
        "/docs",
        "/openapi.json",
        "/redoc",
    }
)


RESERVED_SLUGS = frozenset(
    {"admin", "api", "app", "auth", "billing", "demo", "support", "www", "skyrict"}
)
RESERVED_EMAILS = frozenset(
    {
        "admin@skyrict.com",
        "no-reply@skyrict.com",
        "sales@skyrict.com",
        "support@skyrict.com",
    }
)

SIGNUP_START_LIMIT_KEY = "signup_start_ip"
SIGNUP_CODE_LIMIT_KEY = "signup_code"
SIGNUP_CODE_IP_LIMIT_KEY = "signup_code_ip"
SIGNUP_VERIFY_LIMIT_KEY = "signup_verify"
SIGNUP_CHECK_LIMIT_KEY = "signup_check_ip"


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
DEFAULT_INVITE_ROLE = "standard_user"

PROBLEM_INVITATION_NOT_FOUND = f"{PROBLEM_BASE_URL}/invitation-not-found"
PROBLEM_INVITATION_EXPIRED = f"{PROBLEM_BASE_URL}/invitation-expired"
PROBLEM_INVITATION_ALREADY_USED = f"{PROBLEM_BASE_URL}/invitation-already-used"
PROBLEM_INVITATION_EMAIL_MISMATCH = f"{PROBLEM_BASE_URL}/invitation-email-mismatch"
