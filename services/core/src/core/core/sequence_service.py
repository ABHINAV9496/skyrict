"""Sequence service — tenant-scoped monotonic counters for document numbering.

The service is a thin facade over :class:`SequenceRepositoryPort` so producers
(HR/payroll/finance document numbering) depend on the port, not SQLAlchemy.
"""

from __future__ import annotations

import uuid

from core.db.ports import SequenceRepositoryPort
from core.domain.entities import ErpSequence


class SequenceService:
    """Facade over :class:`SequenceRepositoryPort` for counter access."""

    def __init__(self, repository: SequenceRepositoryPort) -> None:
        self._repository = repository

    async def next(self, *, tenant_id: uuid.UUID, entity: str) -> int:
        """Claim the next number for ``entity`` (race-safe, never reused)."""
        return await self._repository.next_value(tenant_id, entity)

    async def current(self, *, tenant_id: uuid.UUID, entity: str) -> ErpSequence | None:
        """Inspect a counter without advancing it."""
        return await self._repository.get(tenant_id, entity)
