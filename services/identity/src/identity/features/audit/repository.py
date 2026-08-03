"""Audit repository — DB operations for the audit_logs table."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from identity.db.repository import BaseRepository
from identity.models.audit_log import AuditLogModel


class AuditRepository(BaseRepository[AuditLogModel]):
    """Repository for audit log operations."""

    model = AuditLogModel

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
    ) -> AuditLogModel:
        """Create an audit log entry.

        ``hash`` / ``prev_hash`` are filled by the DB trigger
        (``audit_logs_set_hash``); the append-only trigger blocks later
        UPDATE/DELETE on this row.
        """
        entry = AuditLogModel(
            tenant_id=tenant_id,
            actor_user_id=user_id,
            action=action,
            target=target,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return await self.create(entry)

    async def get_by_user(
        self, user_id: str, *, offset: int = 0, limit: int = 50
    ) -> list[AuditLogModel]:
        """Get audit entries for a specific user."""
        stmt = (
            select(AuditLogModel)
            .where(AuditLogModel.actor_user_id == user_id)
            .order_by(AuditLogModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
