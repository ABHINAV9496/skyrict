"""Invitation event producers - structured log events for the invitation lifecycle."""

from __future__ import annotations

import structlog

logger = structlog.get_logger("identity.events.invitations")


async def emit_invitation_created(
    *,
    invitation_id: str,
    tenant_id: str,
    email: str,
    inviter_name: str,
) -> None:
    logger.info(
        "event.invitation.created",
        invitation_id=invitation_id,
        tenant_id=tenant_id,
        email=email,
        inviter_name=inviter_name,
    )


async def emit_invitation_accepted(
    *,
    invitation_id: str,
    tenant_id: str,
    user_id: str,
) -> None:
    logger.info(
        "event.invitation.accepted",
        invitation_id=invitation_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
