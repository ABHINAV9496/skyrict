"""Canonical capability keys for the identity domain.

Capabilities describe *whether a feature is available* for a tenant or user
(platform/toggle surface), distinct from permissions, which describe *what a
user is allowed to do* (RBAC). For example ``auth:invite`` gates the member
invitation flow, while ``invitations:send`` authorizes an individual user to
send one.

Keys are platform-fixed: a capability must be added here AND via migration
before it can be toggled or enforced. Feature/tenant gate enforcement lives in
the auth pipeline; this module is the single source of truth for the keys.
"""

from __future__ import annotations

# Authentication & membership
AUTH_REGISTRATION = "auth:registration"
AUTH_INVITE = "auth:invite"
AUTH_PASSWORD_RESET = "auth:password-reset"
AUTH_PASSKEYS = "auth:passkeys"
AUTH_SSO = "auth:sso"

# Multi-factor authentication (MFA provider registry)
AUTH_MFA_TOTP = "auth:mfa:totp"
AUTH_MFA_RECOVERY_CODES = "auth:mfa:recovery-codes"

# Sessions & devices
SESSION_ROTATION = "session:rotation"
SESSION_TRUSTED_DEVICES = "session:trusted-devices"
SESSION_REVOKE = "session:revoke"

# Handoff tokens
HANDOFF_TOKENS = "handoff.tokens"

# Audit & compliance
AUDIT_EXPORT = "audit:export"

# Every catalogued capability, in catalog order.
CATALOG: tuple[str, ...] = (
    AUTH_REGISTRATION,
    AUTH_INVITE,
    AUTH_PASSWORD_RESET,
    AUTH_PASSKEYS,
    AUTH_SSO,
    AUTH_MFA_TOTP,
    AUTH_MFA_RECOVERY_CODES,
    SESSION_ROTATION,
    SESSION_TRUSTED_DEVICES,
    SESSION_REVOKE,
    HANDOFF_TOKENS,
    AUDIT_EXPORT,
)

ALL_CAPABILITIES: frozenset[str] = frozenset(CATALOG)

# Capability module groupings (for catalog endpoints and UI).
# Each entry: (module_key, module_label, (capability_keys, ...))
CAPABILITY_MODULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "auth",
        "Authentication & membership",
        (AUTH_REGISTRATION, AUTH_INVITE, AUTH_PASSWORD_RESET, AUTH_PASSKEYS, AUTH_SSO),
    ),
    ("mfa", "Multi-factor authentication", (AUTH_MFA_TOTP, AUTH_MFA_RECOVERY_CODES)),
    (
        "session",
        "Sessions & devices",
        (SESSION_ROTATION, SESSION_TRUSTED_DEVICES, SESSION_REVOKE),
    ),
    ("handoff", "Handoff tokens", (HANDOFF_TOKENS,)),
    ("audit", "Audit & compliance", (AUDIT_EXPORT,)),
)


def _assert_catalog_union() -> None:
    """Ensure CAPABILITY_MODULES and CATALOG stay in sync (fail-fast on drift)."""
    module_keys = {key for _, _, keys in CAPABILITY_MODULES for key in keys}
    if module_keys != ALL_CAPABILITIES:
        missing = ALL_CAPABILITIES - module_keys
        orphaned = module_keys - ALL_CAPABILITIES
        msg = "CAPABILITY_MODULES <-> CATALOG mismatch:\n"
        if missing:
            msg += f"  Missing from CAPABILITY_MODULES: {sorted(missing)}\n"
        if orphaned:
            msg += f"  Orphaned in CAPABILITY_MODULES: {sorted(orphaned)}\n"
        raise ValueError(msg)


_assert_catalog_union()

__all__ = [
    "ALL_CAPABILITIES",
    "AUDIT_EXPORT",
    "AUTH_INVITE",
    "AUTH_MFA_RECOVERY_CODES",
    "AUTH_MFA_TOTP",
    "AUTH_PASSKEYS",
    "AUTH_PASSWORD_RESET",
    "AUTH_REGISTRATION",
    "AUTH_SSO",
    "CAPABILITY_MODULES",
    "CATALOG",
    "HANDOFF_TOKENS",
    "SESSION_REVOKE",
    "SESSION_ROTATION",
    "SESSION_TRUSTED_DEVICES",
]
