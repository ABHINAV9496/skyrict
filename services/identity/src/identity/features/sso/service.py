"""SSO service - SAML/OIDC identity provider integration. Not yet implemented."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from identity.features.users.ports import UserRepositoryPort


class SSOService:
    """Handles SAML and OIDC SSO flows.

    The interface is stable but every operation raises NotImplementedError
    rather than returning placeholder authorization URLs.
    """

    def __init__(self, user_repo: UserRepositoryPort) -> None:
        self.user_repo = user_repo

    async def start_oidc_flow(self, provider: str, redirect_uri: str) -> dict[str, Any]:
        """Generate OIDC authorization URL."""
        raise NotImplementedError("OIDC SSO is not yet implemented")

    async def handle_oidc_callback(self, code: str, state: str) -> dict[str, Any]:
        """Exchange OIDC code for tokens, create/find user, return session."""
        raise NotImplementedError("OIDC SSO is not yet implemented")

    async def start_saml_flow(self, provider: str) -> dict[str, Any]:
        """Generate SAML AuthnRequest."""
        raise NotImplementedError("SAML SSO is not yet implemented")

    async def handle_saml_callback(self, saml_response: str) -> dict[str, Any]:
        """Process SAML Response assertion."""
        raise NotImplementedError("SAML SSO is not yet implemented")
