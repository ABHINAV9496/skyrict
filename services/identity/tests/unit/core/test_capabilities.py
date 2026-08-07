"""Unit tests for the platform capability registry (identity/core/capabilities.py).

Capabilities are feature-availability toggles, distinct from RBAC permissions.
These tests guard the invariant that CATALOG, ALL_CAPABILITIES and
CAPABILITY_MODULES never drift apart.
"""

from __future__ import annotations

from identity.core.capabilities import (
    ALL_CAPABILITIES,
    AUDIT_EXPORT,
    AUTH_INVITE,
    AUTH_MFA_RECOVERY_CODES,
    AUTH_MFA_TOTP,
    AUTH_PASSKEYS,
    AUTH_PASSWORD_RESET,
    AUTH_REGISTRATION,
    AUTH_SSO,
    CAPABILITY_MODULES,
    CATALOG,
    HANDOFF_TOKENS,
    SESSION_REVOKE,
    SESSION_ROTATION,
    SESSION_TRUSTED_DEVICES,
)


class TestCatalogInvariants:
    def test_catalog_matches_all_capabilities(self):
        assert set(CATALOG) == set(ALL_CAPABILITIES)

    def test_catalog_is_deduplicated(self):
        assert len(CATALOG) == len(set(CATALOG))

    def test_catalog_is_nonempty(self):
        assert len(CATALOG) > 0

    def test_modules_cover_catalog_exactly(self):
        module_keys = {key for _, _, keys in CAPABILITY_MODULES for key in keys}
        assert module_keys == set(CATALOG)

    def test_no_capability_appears_in_two_modules(self):
        seen: dict[str, str] = {}
        for module_key, _, keys in CAPABILITY_MODULES:
            for key in keys:
                assert key not in seen, f"{key} in both {seen[key]} and {module_key}"
                seen[key] = module_key

    def test_module_keys_and_labels_are_consistent(self):
        labels = [module_key for module_key, _, _ in CAPABILITY_MODULES]
        assert len(labels) == len(set(labels))


class TestCapabilityKeys:
    def test_expected_auth_capabilities_present(self):
        expected = {
            AUTH_REGISTRATION,
            AUTH_INVITE,
            AUTH_PASSWORD_RESET,
            AUTH_PASSKEYS,
            AUTH_SSO,
            AUTH_MFA_TOTP,
            AUTH_MFA_RECOVERY_CODES,
        }
        assert expected <= ALL_CAPABILITIES

    def test_expected_session_and_handoff_capabilities_present(self):
        expected = {
            SESSION_ROTATION,
            SESSION_TRUSTED_DEVICES,
            SESSION_REVOKE,
            HANDOFF_TOKENS,
        }
        assert expected <= ALL_CAPABILITIES

    def test_audit_export_present(self):
        assert AUDIT_EXPORT in ALL_CAPABILITIES
