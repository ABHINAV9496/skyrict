"""Audit repository - DB operations for the shared ``audit_logs`` table.

All SQLAlchemy stays in this file. The append-only + hash-chain + RLS behavior
is enforced by identity's DB triggers/policies; this repository only appends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.features.audit.models.audit_log import AuditLogModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class AuditRepository:
    """Repository for audit log persistence (implements ``AuditRepositoryPort``)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
    ) -> None:
        """Append one audit log entry.

        ``hash`` / ``prev_hash`` are filled by the DB trigger
        (``audit_logs_set_hash``); the append-only trigger blocks later
        UPDATE/DELETE on this row.
        """
        model = AuditLogModel(
            tenant_id=tenant_id,
            actor_user_id=user_id,
            action=action,
            target=target,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.session.add(model)
        await self.session.flush()
