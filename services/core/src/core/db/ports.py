"""Cross-cutting repository ports for core infrastructure (sequence, audit).

Declares what the repositories must offer so services depend on these Protocols
(hexagonal "ports") rather than the concrete SQLAlchemy implementations. Both
are tenant-scoped; every probe takes an explicit ``tenant_id`` and the session
is additionally bound by RLS (``app.current_tenant_id``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from core.domain.entities import AuditLogEntry, ErpSequence


class SequenceRepositoryPort(Protocol):
    """Persistence contract for the tenant-scoped document counters."""

    async def next_value(self, tenant_id: uuid.UUID, entity: str) -> int: ...

    async def get(self, tenant_id: uuid.UUID, entity: str) -> ErpSequence | None: ...


class AuditLogRepositoryPort(Protocol):
    """Persistence contract for the append-only core audit trail.

    There is deliberately NO update/delete: the log is immutable (DB trigger).
    """

    async def add(self, entry: AuditLogEntry) -> AuditLogEntry: ...

    async def list(
        self,
        tenant_id: uuid.UUID,
        *,
        action: str | None = None,
        actor_user_id: uuid.UUID | None = None,
        q: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[AuditLogEntry]: ...

    async def get(self, tenant_id: uuid.UUID, entry_id: uuid.UUID) -> AuditLogEntry | None: ...

    async def count(
        self,
        tenant_id: uuid.UUID,
        *,
        action: str | None = None,
        actor_user_id: uuid.UUID | None = None,
        q: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> int: ...
