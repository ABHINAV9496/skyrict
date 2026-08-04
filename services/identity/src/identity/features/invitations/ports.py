"""Invitation repository port — the persistence contract the invitation service depends on.

Ports abstract persistence only (never business rules). Methods accept and
return domain entities; SQLAlchemy lives in the concrete implementation
``identity.features.invitations.repository``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from identity.domain.entities import Invitation

if TYPE_CHECKING:
    import uuid


class InvitationRepositoryPort(Protocol):
    async def create(self, invitation: Invitation) -> Invitation: ...

    async def get_by_token(self, token: str) -> Invitation | None: ...

    async def mark_used(
        self, invitation_id: str | uuid.UUID, user_id: str | uuid.UUID
    ) -> Invitation: ...

    async def list_by_tenant(
        self, tenant_id: str | uuid.UUID, *, offset: int = 0, limit: int = 20
    ) -> list[Invitation]: ...
