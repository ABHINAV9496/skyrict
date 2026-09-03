"""Audit repository - DB operations for the audit_logs table.

All SQLAlchemy stays in this file. Service-facing methods accept and return
domain entities (``identity.domain.entities.AuditLog``).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from identity.db.repository import SqlRepository
from identity.domain.entities import AuditLog
from identity.models.audit_log import AuditLogModel


def _from_orm(model: AuditLogModel) -> AuditLog:
    """Map an ORM model to a domain entity."""
    return AuditLog(
        id=model.id,
        tenant_id=model.tenant_id,
        action=model.action,
        target=model.target,
        actor_user_id=model.actor_user_id,
        details=model.details,
        ip_address=model.ip_address,
        user_agent=model.user_agent,
        hash=model.hash,
        prev_hash=model.prev_hash,
        created_at=model.created_at,
    )


class AuditRepository(SqlRepository):
    """Repository for audit log persistence (implements ``AuditRepositoryPort``)."""

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
    ) -> AuditLog:
        """Create an audit log entry.

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
        await self.session.refresh(model)
        return _from_orm(model)

    async def get_by_user(
        self, user_id: str | uuid.UUID, *, offset: int = 0, limit: int = 50
    ) -> list[AuditLog]:
        """Get audit entries for a specific user, newest first."""
        stmt = (
            select(AuditLogModel)
            .where(AuditLogModel.actor_user_id == user_id)
            .order_by(AuditLogModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [_from_orm(model) for model in result.scalars().all()]
