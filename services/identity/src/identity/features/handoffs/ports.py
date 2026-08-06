"""Handoff repository port — the persistence contract the handoff service depends on.

Ports abstract persistence only (never business rules). Methods accept and
return domain entities; SQLAlchemy lives in the concrete implementation
``identity.features.handoffs.repository``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from identity.domain.entities import Handoff

if TYPE_CHECKING:
    import uuid


class HandoffRepositoryPort(Protocol):
    async def create(self, handoff: Handoff) -> Handoff: ...

    async def get_by_hash(self, token_hash: str) -> Handoff | None: ...

    async def mark_consumed(self, handoff_id: str | uuid.UUID) -> Handoff | None: ...
