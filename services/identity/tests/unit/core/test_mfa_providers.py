"""Unit tests for the MFA provider registry (identity/core/mfa_providers.py).

Guards the invariants: provider keys are unique and stable, every provider
links to a known capability, and the index maps never drift from the
canonical catalog.
"""

from __future__ import annotations

import pytest

from identity.core.capabilities import AUTH_MFA_RECOVERY_CODES, AUTH_MFA_TOTP
from identity.core.mfa_providers import (
    ALL_MFA_PROVIDER_KEYS,
    MFA_PROVIDERS,
    MFA_PROVIDERS_BY_KEY,
    PROVIDER_BACKUP_CODE,
    PROVIDER_TOTP,
    available_provider_keys,
    get_provider,
    is_known_provider,
)


class TestRegistryInvariants:
    def test_provider_keys_are_unique(self) -> None:
        keys = [provider.key for provider in MFA_PROVIDERS]
        assert len(keys) == len(set(keys))

    def test_index_maps_cover_catalog_exactly(self) -> None:
        keys = {provider.key for provider in MFA_PROVIDERS}
        assert set(MFA_PROVIDERS_BY_KEY) == keys
        assert keys == ALL_MFA_PROVIDER_KEYS

    def test_providers_reference_known_capabilities(self) -> None:
        capabilities = {provider.capability for provider in MFA_PROVIDERS}
        assert capabilities <= {AUTH_MFA_TOTP, AUTH_MFA_RECOVERY_CODES}

    def test_backup_codes_never_stand_alone(self) -> None:
        keys = {provider.key for provider in MFA_PROVIDERS}
        assert PROVIDER_TOTP in keys
        assert PROVIDER_BACKUP_CODE in keys


class TestProviderLookup:
    def test_get_provider_returns_metadata(self) -> None:
        provider = get_provider(PROVIDER_TOTP)

        assert provider.key == PROVIDER_TOTP
        assert provider.capability == AUTH_MFA_TOTP
        assert provider.requires_setup is True

    def test_get_provider_unknown_raises(self) -> None:
        with pytest.raises(ValueError):
            get_provider("sms")

    def test_is_known_provider(self) -> None:
        assert is_known_provider(PROVIDER_TOTP) is True
        assert is_known_provider(PROVIDER_BACKUP_CODE) is True
        assert is_known_provider("sms") is False

    def test_available_provider_keys_ordered_by_priority(self) -> None:
        keys = available_provider_keys()

        priorities = [MFA_PROVIDERS_BY_KEY[key].priority for key in keys]
        assert priorities == sorted(priorities)
        assert keys[0] == PROVIDER_TOTP
        assert keys[-1] == PROVIDER_BACKUP_CODE
