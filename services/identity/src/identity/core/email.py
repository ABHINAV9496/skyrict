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
