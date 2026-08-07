"""Canonical audit event keys for the identity domain.

Single source of truth for the free-form ``action`` strings written to
``audit_logs``. Services must reference these constants instead of hardcoding
strings so the event vocabulary stays greppable and drift-checked against the
catalog grouping below.

The catalog intentionally includes events for surfaces under construction
(membership lifecycle, session revocation, handoff tokens, password reset);
their producers are wired in as those flows land.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
AUTH_LOGIN_SUCCESS = "auth.login.success"
AUTH_LOGIN_FAILED = "auth.login.failed"
AUTH_LOGIN_MFA_CHALLENGED = "auth.login.mfa_challenged"
AUTH_LOGIN_MFA_VERIFY_FAILED = "auth.login.mfa.verify_failed"
AUTH_LOGIN_MFA_VERIFIED = "auth.login.mfa_verified"
AUTH_LOGIN_NEW_DEVICE_ALERT = "auth.login.new_device_alert"
AUTH_REGISTER_SUCCESS = "auth.register.success"
AUTH_REFRESH_SUCCESS = "auth.refresh.success"
AUTH_REFRESH_REUSE_DETECTED = "auth.refresh.reuse_detected"
AUTH_LOGOUT = "auth.logout"
AUTH_PASSWORD_CHANGED = "auth.password.changed"
AUTH_PASSWORD_RESET_REQUESTED = "auth.password.reset_requested"
AUTH_PASSWORD_RESET_COMPLETED = "auth.password.reset_completed"

# ---------------------------------------------------------------------------
# Multi-factor authentication
# ---------------------------------------------------------------------------
MFA_SETUP_INITIATED = "mfa.setup.initiated"
MFA_ENABLED = "mfa.enabled"
MFA_DISABLED = "mfa.disabled"
MFA_RESET = "mfa.reset"
MFA_VERIFY_BACKUP_CODE_USED = "mfa.verify.backup_code_used"
MFA_RECOVERY_CODES_REGENERATED = "mfa.recovery_codes.regenerated"

# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------
INVITATION_CREATED = "invitation.created"
INVITATION_ACCEPTED = "invitation.accepted"
INVITATION_EXPIRED = "invitation.expired"

# ---------------------------------------------------------------------------
# Membership lifecycle
# ---------------------------------------------------------------------------
MEMBERSHIP_ACTIVATED = "membership.activated"
MEMBERSHIP_SUSPENDED = "membership.suspended"
MEMBERSHIP_REINSTATED = "membership.reinstated"
MEMBERSHIP_LEFT = "membership.left"

# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
SESSION_CREATED = "session.created"
SESSION_REVOKED = "session.revoked"
SESSION_REVOKED_ALL = "session.revoked_all"
SESSION_TRUSTED = "session.trusted"

# ---------------------------------------------------------------------------
# Handoff tokens
# ---------------------------------------------------------------------------
HANDOFF_ISSUED = "handoff.issued"
HANDOFF_REDEEMED = "handoff.redeemed"

# Every catalogued audit event, in catalog order.
CATALOG: tuple[str, ...] = (
    AUTH_LOGIN_SUCCESS,
    AUTH_LOGIN_FAILED,
    AUTH_LOGIN_MFA_CHALLENGED,
    AUTH_LOGIN_MFA_VERIFY_FAILED,
    AUTH_LOGIN_MFA_VERIFIED,
    AUTH_LOGIN_NEW_DEVICE_ALERT,
    AUTH_REGISTER_SUCCESS,
    AUTH_REFRESH_SUCCESS,
    AUTH_REFRESH_REUSE_DETECTED,
    AUTH_LOGOUT,
    AUTH_PASSWORD_CHANGED,
    AUTH_PASSWORD_RESET_REQUESTED,
    AUTH_PASSWORD_RESET_COMPLETED,
    MFA_SETUP_INITIATED,
    MFA_ENABLED,
    MFA_DISABLED,
    MFA_RESET,
    MFA_VERIFY_BACKUP_CODE_USED,
    MFA_RECOVERY_CODES_REGENERATED,
    INVITATION_CREATED,
    INVITATION_ACCEPTED,
    INVITATION_EXPIRED,
    MEMBERSHIP_ACTIVATED,
    MEMBERSHIP_SUSPENDED,
    MEMBERSHIP_REINSTATED,
    MEMBERSHIP_LEFT,
    SESSION_CREATED,
    SESSION_REVOKED,
    SESSION_REVOKED_ALL,
    SESSION_TRUSTED,
    HANDOFF_ISSUED,
    HANDOFF_REDEEMED,
)

ALL_AUDIT_EVENTS: frozenset[str] = frozenset(CATALOG)

# Event module groupings (for catalog endpoints and UI).
# Each entry: (module_key, module_label, (event_keys, ...))
AUDIT_EVENT_MODULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "auth",
        "Authentication",
        (
            AUTH_LOGIN_SUCCESS,
            AUTH_LOGIN_FAILED,
            AUTH_LOGIN_MFA_CHALLENGED,
            AUTH_LOGIN_MFA_VERIFY_FAILED,
            AUTH_LOGIN_MFA_VERIFIED,
            AUTH_LOGIN_NEW_DEVICE_ALERT,
            AUTH_REGISTER_SUCCESS,
            AUTH_REFRESH_SUCCESS,
            AUTH_REFRESH_REUSE_DETECTED,
            AUTH_LOGOUT,
            AUTH_PASSWORD_CHANGED,
            AUTH_PASSWORD_RESET_REQUESTED,
            AUTH_PASSWORD_RESET_COMPLETED,
        ),
    ),
    (
        "mfa",
        "Multi-factor authentication",
        (
            MFA_SETUP_INITIATED,
            MFA_ENABLED,
            MFA_DISABLED,
            MFA_RESET,
            MFA_VERIFY_BACKUP_CODE_USED,
            MFA_RECOVERY_CODES_REGENERATED,
        ),
    ),
    (
        "invitations",
        "User invitations",
        (INVITATION_CREATED, INVITATION_ACCEPTED, INVITATION_EXPIRED),
    ),
    (
        "membership",
        "Membership lifecycle",
        (MEMBERSHIP_ACTIVATED, MEMBERSHIP_SUSPENDED, MEMBERSHIP_REINSTATED, MEMBERSHIP_LEFT),
    ),
    (
        "session",
        "Sessions",
        (SESSION_CREATED, SESSION_REVOKED, SESSION_REVOKED_ALL, SESSION_TRUSTED),
    ),
    ("handoff", "Handoff tokens", (HANDOFF_ISSUED, HANDOFF_REDEEMED)),
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
    "AUTH_LOGIN_FAILED",
    "AUTH_LOGIN_MFA_CHALLENGED",
    "AUTH_LOGIN_MFA_VERIFIED",
    "AUTH_LOGIN_MFA_VERIFY_FAILED",
    "AUTH_LOGIN_NEW_DEVICE_ALERT",
    "AUTH_LOGIN_SUCCESS",
    "AUTH_LOGOUT",
    "AUTH_PASSWORD_CHANGED",
    "AUTH_PASSWORD_RESET_COMPLETED",
    "AUTH_PASSWORD_RESET_REQUESTED",
    "AUTH_REFRESH_REUSE_DETECTED",
    "AUTH_REFRESH_SUCCESS",
    "AUTH_REGISTER_SUCCESS",
    "CATALOG",
    "HANDOFF_ISSUED",
    "HANDOFF_REDEEMED",
    "INVITATION_ACCEPTED",
    "INVITATION_CREATED",
    "INVITATION_EXPIRED",
    "MEMBERSHIP_ACTIVATED",
    "MEMBERSHIP_LEFT",
    "MEMBERSHIP_REINSTATED",
    "MEMBERSHIP_SUSPENDED",
    "MFA_DISABLED",
    "MFA_ENABLED",
    "MFA_RECOVERY_CODES_REGENERATED",
    "MFA_RESET",
    "MFA_SETUP_INITIATED",
    "MFA_VERIFY_BACKUP_CODE_USED",
    "SESSION_CREATED",
    "SESSION_REVOKED",
    "SESSION_REVOKED_ALL",
    "SESSION_TRUSTED",
]
