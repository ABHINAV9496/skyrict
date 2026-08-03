"""MFA service — TOTP setup, verification, backup codes. Not yet implemented."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid

    from identity.features.users.ports import UserRepositoryPort


class MFAService:
    """Handles multi-factor authentication setup and verification.

    The interface is stable but every operation raises NotImplementedError
    rather than returning placeholder or insecure data (e.g. accepting any
    six-digit TOTP code).
    """

    def __init__(self, user_repo: UserRepositoryPort) -> None:
        self.user_repo = user_repo

    async def setup_totp(self, user_id: uuid.UUID) -> dict[str, Any]:
        """Generate a TOTP secret and provisioning URI for a user."""
        raise NotImplementedError("MFA setup is not yet implemented")

    async def verify_totp(self, user_id: uuid.UUID, code: str) -> bool:
        """Verify a TOTP code."""
        raise NotImplementedError("MFA verification is not yet implemented")

    async def enable_mfa(self, user_id: uuid.UUID, secret: str, code: str) -> None:
        """Enable MFA after verifying the first TOTP code."""
        raise NotImplementedError("MFA enable is not yet implemented")

    async def disable_mfa(self, user_id: uuid.UUID, password: str) -> None:
        """Disable MFA after password confirmation."""
        raise NotImplementedError("MFA disable is not yet implemented")
