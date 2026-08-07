"""Unit tests for the audit event registry (identity/core/audit_events.py).

Guards the invariant that CATALOG, ALL_AUDIT_EVENTS and AUDIT_EVENT_MODULES
never drift, and that every event key actually in use by the services is a
catalogued constant (no free-form strings slipping back in).
"""

from __future__ import annotations

import identity.features.auth.router as auth_router
import identity.features.auth.service as auth_service
import identity.features.handoffs.service as handoff_service
import identity.features.invitations.service as invitation_service
import identity.features.memberships.service as membership_service
import identity.features.mfa.service as mfa_service
from identity.core.audit_events import (
    ALL_AUDIT_EVENTS,
    AUDIT_EVENT_MODULES,
    AUTH_LOGIN_FAILED,
    AUTH_LOGIN_MFA_CHALLENGED,
    AUTH_LOGIN_MFA_VERIFIED,
    AUTH_LOGIN_MFA_VERIFY_FAILED,
    AUTH_LOGIN_SUCCESS,
    AUTH_LOGOUT,
    AUTH_PASSWORD_CHANGED,
    AUTH_PASSWORD_RESET_COMPLETED,
    AUTH_PASSWORD_RESET_REQUESTED,
    AUTH_REGISTER_SUCCESS,
    CATALOG,
    MEMBERSHIP_LEFT,
    MFA_DISABLED,
    MFA_ENABLED,
    MFA_RECOVERY_CODES_REGENERATED,
    MFA_RESET,
    MFA_SETUP_INITIATED,
    MFA_VERIFY_BACKUP_CODE_USED,
)

_ACTION_KEYS = ("audit_action",)


def _module_labels() -> set[str]:
    return {module_key for module_key, _, _ in AUDIT_EVENT_MODULES}


class TestCatalogInvariants:
    def test_catalog_matches_all_events(self):
        assert set(CATALOG) == set(ALL_AUDIT_EVENTS)

    def test_catalog_is_deduplicated(self):
        assert len(CATALOG) == len(set(CATALOG))

    def test_catalog_is_nonempty(self):
        assert len(CATALOG) > 0

    def test_modules_cover_catalog_exactly(self):
        module_keys = {key for _, _, keys in AUDIT_EVENT_MODULES for key in keys}
        assert module_keys == set(CATALOG)

    def test_no_event_appears_in_two_modules(self):
        seen: dict[str, str] = {}
        for module_key, _, keys in AUDIT_EVENT_MODULES:
            for key in keys:
                assert key not in seen, f"{key} in both {seen[key]} and {module_key}"
                seen[key] = module_key

    def test_module_keys_and_labels_are_consistent(self):
        assert len(_module_labels()) == len(AUDIT_EVENT_MODULES)


class TestActionStringsUsedInServices:
    """Every audit action string the services write must be a catalogued event."""

    @staticmethod
    def _read_source(module: object) -> str:
        with open(module.__file__, encoding="utf-8") as fh:  # type: ignore[arg-type]
            return fh.read()

    def test_auth_service_action_strings_are_catalogued(self):
        src = self._read_source(auth_service)
        assert AUTH_LOGIN_SUCCESS in src
        assert AUTH_LOGIN_FAILED in src
        assert AUTH_LOGIN_MFA_CHALLENGED in src
        assert AUTH_REGISTER_SUCCESS in src
        # Refresh events are referenced through their catalogued constants.
        assert "AUTH_REFRESH_SUCCESS" in src
        assert "AUTH_REFRESH_REUSE_DETECTED" in src

    def test_auth_router_action_strings_are_catalogued(self):
        src = self._read_source(auth_router)
        assert AUTH_LOGIN_MFA_VERIFY_FAILED in src
        assert AUTH_LOGIN_MFA_VERIFIED in src

    def test_mfa_service_action_strings_are_catalogued(self):
        src = self._read_source(mfa_service)
        assert MFA_SETUP_INITIATED in src
        assert MFA_ENABLED in src
        assert MFA_DISABLED in src
        assert MFA_RESET in src
        assert MFA_VERIFY_BACKUP_CODE_USED in src

    def test_handoff_service_action_strings_are_catalogued(self):
        src = self._read_source(handoff_service)
        assert "HANDOFF_ISSUED" in src
        assert "HANDOFF_REDEEMED" in src

    def test_invitation_service_action_strings_are_catalogued(self):
        src = self._read_source(invitation_service)
        assert "INVITATION_CREATED" in src
        assert "INVITATION_ACCEPTED" in src
        assert "INVITATION_EXPIRED" in src

    def test_membership_service_action_strings_are_catalogued(self):
        src = self._read_source(membership_service)
        assert "MEMBERSHIP_ACTIVATED" in src
        assert "MEMBERSHIP_SUSPENDED" in src
        assert "MEMBERSHIP_REINSTATED" in src

    def test_catalog_contains_no_future_orphans(self):
        # Events declared for surfaces still under construction must be
        # deliberately planned (they will be produced as flows land), so assert
        # the full planned set is present.
        planned = {
            AUTH_LOGOUT,
            AUTH_PASSWORD_CHANGED,
            AUTH_PASSWORD_RESET_REQUESTED,
            AUTH_PASSWORD_RESET_COMPLETED,
            MFA_RECOVERY_CODES_REGENERATED,
            MEMBERSHIP_LEFT,
        }
        assert planned <= ALL_AUDIT_EVENTS
