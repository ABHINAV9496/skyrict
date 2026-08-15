"""Audit service — the shared, tenant-scoped audit facade for core (ERP) actions.

Every mutation goes through ``log`` (per docs/modules/hr-payroll.md §step 4);
the repository appends to ``core_audit_logs`` where the DB trigger builds the
SHA-256 hash chain and the append-only trigger blocks later UPDATE/DELETE.
Producers must use the constants from ``core.core.audit_events`` for ``action``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.core.audit_events import ALL_AUDIT_EVENTS
from core.domain.entities import AuditLogEntry

if TYPE_CHECKING:
    import uuid

    from core.db.ports import AuditLogRepositoryPort


class AuditService:
    """Facade over :class:`AuditLogRepositoryPort` for audit writes and reads."""

    def __init__(self, repository: AuditLogRepositoryPort) -> None:
        self._repository = repository

    async def log(
        self,
        *,
        action: str,
        target: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditLogEntry:
        """Append one immutable audit event (hash chain computed by the trigger)."""
        if action not in ALL_AUDIT_EVENTS:
            raise ValueError(
                f"unknown audit action {action!r}; use core.core.audit_events constants"
            )
        return await self._repository.add(
            AuditLogEntry(
                tenant_id=tenant_id,
                action=action,
                target=target,
                actor_user_id=user_id,
                details=details,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

    async def feed(
        self,
        tenant_id: uuid.UUID,
        *,
        action: str | None = None,
        limit: int = 100,
    ) -> list[AuditLogEntry]:
        """Return the tenant's audit trail, newest first, optionally filtered."""
        return await self._repository.list(tenant_id, action=action, limit=limit)
