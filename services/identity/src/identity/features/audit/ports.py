"""Audit repository port - the persistence contract the audit service depends on.

Ports abstract persistence only (never business rules). Methods accept and
return domain entities; SQLAlchemy lives in the concrete implementation
``identity.features.audit.repository``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from identity.domain.entities import AuditLog

if TYPE_CHECKING:
    import uuid


class AuditRepositoryPort(Protocol):
    """Persistence operations for the append-only audit log."""

    async def log(
        self,
        *,
        tenant_id: str,
        user_id: str | None = None,
        action: str,
        target: str,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog: ...

    async def get_by_user(
        self, user_id: str | uuid.UUID, *, offset: int = 0, limit: int = 50
    ) -> list[AuditLog]: ...
