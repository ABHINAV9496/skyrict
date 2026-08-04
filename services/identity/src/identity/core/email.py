"""Email delivery port and transports.

No production mail infrastructure exists yet, so the wired transport is
``LogEmailService`` (logs the payload). Swap in a real SMTP/provider transport
behind the same ``EmailService`` protocol without touching callers.
"""

from __future__ import annotations

from typing import Protocol

import structlog

logger = structlog.get_logger("identity.email")


class EmailService(Protocol):
    """Delivery contract for transactional email."""

    async def send_verification(
        self, *, to: str, full_name: str, token: str, base_url: str | None = None
    ) -> None: ...

    async def send_invitation(
        self,
        *,
        to: str,
        inviter_name: str,
        organization_name: str,
        token: str,
        base_url: str | None = None,
    ) -> None: ...

    async def send_security_alert(
        self,
        *,
        to: str,
        full_name: str,
        event_type: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None: ...


class LogEmailService:
    """Transport that logs the verification payload (dev/test default)."""

    async def send_verification(
        self, *, to: str, full_name: str, token: str, base_url: str | None = None
    ) -> None:
        """Record the verification email instead of sending it."""
        logger.info(
            "email.verification.sent",
            to=to,
            full_name=full_name,
            verification_token=token,
            base_url=base_url,
        )

    async def send_invitation(
        self,
        *,
        to: str,
        inviter_name: str,
        organization_name: str,
        token: str,
        base_url: str | None = None,
    ) -> None:
        logger.info(
            "email.invitation.sent",
            to=to,
            inviter_name=inviter_name,
            organization_name=organization_name,
            invitation_token=token,
            base_url=base_url,
        )

    async def send_security_alert(
        self,
        *,
        to: str,
        full_name: str,
        event_type: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        logger.info(
            "email.security_alert.sent",
            to=to,
            full_name=full_name,
            event_type=event_type,
            ip_address=ip_address,
            user_agent=user_agent,
        )
