"""Handoff service — issue and redeem single-use onboarding handoff tokens.

The wizard and BFF pass control across requests by exchanging an opaque,
single-use token that carries the in-flight payload so the exact step can be
resumed. Only the SHA-256 hash is stored; the raw token is returned exactly
once at issue time.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from identity.core.audit_events import HANDOFF_ISSUED, HANDOFF_REDEEMED
from identity.core.config import settings
from identity.core.security import hash_handoff_token
from identity.domain.entities import Handoff
from identity.features.handoffs.ports import HandoffRepositoryPort
from skyrict_common.exceptions import (
    HandoffTokenAlreadyUsedError,
    HandoffTokenExpiredError,
    HandoffTokenNotFoundError,
)

if TYPE_CHECKING:
    from identity.features.audit.service import AuditService


class HandoffService:
    """Manages the single-use handoff token lifecycle."""

    def __init__(self, handoff_repo: HandoffRepositoryPort, audit_service: AuditService) -> None:
        self.handoff_repo = handoff_repo
        self.audit_service = audit_service

    async def issue(
        self,
        *,
        purpose: str,
        payload: dict[str, Any] | None = None,
        tenant_id: str | uuid.UUID | None = None,
        created_by_user_id: str | uuid.UUID | None = None,
    ) -> tuple[Handoff, str]:
        """Create a handoff token and return it with the raw (once-only) value."""
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(minutes=settings.HANDOFF_TOKEN_EXPIRE_MINUTES)
        handoff = await self.handoff_repo.create(
            Handoff(
                purpose=purpose,
                token_hash=hash_handoff_token(token),
                payload=payload or {},
                tenant_id=uuid.UUID(str(tenant_id)) if tenant_id else None,
                created_by_user_id=uuid.UUID(str(created_by_user_id))
                if created_by_user_id
                else None,
                expires_at=expires_at,
            )
        )
        await self.audit_service.log(
            action=HANDOFF_ISSUED,
            target=f"handoff:{handoff.id}",
            user_id=str(created_by_user_id) if created_by_user_id else None,
            tenant_id=str(tenant_id) if tenant_id else None,
            details={"purpose": purpose},
        )
        return handoff, token

    async def redeem(
        self,
        *,
        token: str,
        purpose: str | None = None,
    ) -> Handoff:
        """Redeem a single-use handoff token, returning its carried payload.

        Raises:
            HandoffTokenNotFoundError: Unknown token.
            HandoffTokenExpiredError: Token past its TTL.
            HandoffTokenAlreadyUsedError: Token already redeemed.
        """
        handoff = await self.handoff_repo.get_by_hash(hash_handoff_token(token))
        if handoff is None:
            raise HandoffTokenNotFoundError("Invalid handoff token")

        if purpose is not None and handoff.purpose != purpose:
            raise HandoffTokenNotFoundError("Handoff token purpose mismatch")

        if handoff.expires_at < datetime.now(UTC):
            raise HandoffTokenExpiredError("Handoff token has expired")

        if handoff.consumed_at is not None:
            raise HandoffTokenAlreadyUsedError("Handoff token has already been used")

        assert handoff.id is not None
        consumed = await self.handoff_repo.mark_consumed(handoff.id)
        assert consumed is not None

        await self.audit_service.log(
            action=HANDOFF_REDEEMED,
            target=f"handoff:{handoff.id}",
            user_id=str(handoff.created_by_user_id) if handoff.created_by_user_id else None,
            tenant_id=str(handoff.tenant_id) if handoff.tenant_id else None,
            details={"purpose": handoff.purpose},
        )
        return consumed
