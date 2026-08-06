"""Canonical MFA provider registry for the identity domain.

Providers describe *which second-factor mechanisms exist* (TOTP, backup
codes, and later passkeys, email OTP, etc.). The registry is the single
source of truth for provider keys, their human labels, and the capability
that gates each provider. Services and routers must reference the provider
constants instead of hardcoding keys so the vocabulary stays greppable and
drift-checked against the capability catalog.

``backup_code`` is listed as a provider but is a *recovery* channel rather
than a primary factor: it is generated during enrollment and can never be
the only enrolled factor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from identity.core.capabilities import ALL_CAPABILITIES, AUTH_MFA_RECOVERY_CODES, AUTH_MFA_TOTP

PROVIDER_TOTP: Final = "totp"
PROVIDER_BACKUP_CODE: Final = "backup_code"


@dataclass(frozen=True)
class MFAProvider:
    """Description of one enrolled second-factor mechanism."""

    key: str
    label: str
    description: str
    capability: str
    requires_setup: bool
    priority: int = 100


MFA_PROVIDERS: tuple[MFAProvider, ...] = (
    MFAProvider(
        key=PROVIDER_TOTP,
        label="Authenticator app (TOTP)",
        description="Six-digit codes from an authenticator app (e.g. Google Authenticator).",
        capability=AUTH_MFA_TOTP,
        requires_setup=True,
        priority=10,
    ),
    MFAProvider(
        key=PROVIDER_BACKUP_CODE,
        label="Backup codes",
        description="Ten single-use recovery codes generated at enrollment.",
        capability=AUTH_MFA_RECOVERY_CODES,
        requires_setup=True,
        priority=20,
    ),
)

MFA_PROVIDERS_BY_KEY: dict[str, MFAProvider] = {
    provider.key: provider for provider in MFA_PROVIDERS
}
ALL_MFA_PROVIDER_KEYS: frozenset[str] = frozenset(MFA_PROVIDERS_BY_KEY)


def get_provider(key: str) -> MFAProvider:
    """Return the provider metadata for ``key`` or raise ``ValueError``."""
    try:
        return MFA_PROVIDERS_BY_KEY[key]
    except KeyError:
        raise ValueError(f"Unknown MFA provider: {key!r}") from None


def is_known_provider(key: str) -> bool:
    """Return whether ``key`` names a registered provider."""
    return key in MFA_PROVIDERS_BY_KEY


def available_provider_keys() -> tuple[str, ...]:
    """Provider keys ordered by priority (for enrollment/availability UI)."""
    return tuple(provider.key for provider in sorted(MFA_PROVIDERS, key=lambda p: p.priority))


def _assert_registry_consistency() -> None:
    """Fail fast on drift between the catalog, capability links, and index maps."""
    keys = {provider.key for provider in MFA_PROVIDERS}
    if len(keys) != len(MFA_PROVIDERS):
        raise ValueError("Duplicate MFA provider keys in MFA_PROVIDERS")
    unknown = {provider.capability for provider in MFA_PROVIDERS} - ALL_CAPABILITIES
    if unknown:
        raise ValueError(f"MFA providers reference unknown capabilities: {sorted(unknown)}")
    if set(MFA_PROVIDERS_BY_KEY) != keys:
        raise ValueError("MFA_PROVIDERS_BY_KEY drift from MFA_PROVIDERS")
    if keys != ALL_MFA_PROVIDER_KEYS:
        raise ValueError("ALL_MFA_PROVIDER_KEYS drift from MFA_PROVIDERS")
    if available_provider_keys() != tuple(
        p.key for p in sorted(MFA_PROVIDERS, key=lambda p: p.priority)
    ):
        raise ValueError("available_provider_keys drift from MFA_PROVIDERS ordering")


_assert_registry_consistency()

__all__ = [
    "ALL_MFA_PROVIDER_KEYS",
    "MFA_PROVIDERS",
    "MFA_PROVIDERS_BY_KEY",
    "PROVIDER_BACKUP_CODE",
    "PROVIDER_TOTP",
    "MFAProvider",
    "available_provider_keys",
    "get_provider",
    "is_known_provider",
]
