"""Passkey (WebAuthn) service - registration and authentication. Not yet implemented."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid

    from identity.features.users.ports import UserRepositoryPort


class PasskeyService:
    """Handles WebAuthn/FIDO2 passkey operations.

    The interface is stable but every operation raises NotImplementedError
    rather than returning placeholder challenges.
    """

    def __init__(self, user_repo: UserRepositoryPort) -> None:
        self.user_repo = user_repo

    async def start_registration(self, user_id: uuid.UUID) -> dict[str, Any]:
        """Initiate passkey registration - return challenge options."""
        raise NotImplementedError("Passkey registration is not yet implemented")

    async def complete_registration(
        self, user_id: uuid.UUID, credential: dict[str, Any]
    ) -> dict[str, Any]:
        """Complete passkey registration after browser ceremony."""
        raise NotImplementedError("Passkey registration is not yet implemented")

    async def start_authentication(self, email: str) -> dict[str, Any]:
        """Initiate passkey authentication - return challenge options."""
        raise NotImplementedError("Passkey authentication is not yet implemented")

    async def complete_authentication(self, credential: dict[str, Any]) -> dict[str, Any]:
        """Complete passkey authentication after browser ceremony."""
        raise NotImplementedError("Passkey authentication is not yet implemented")
