"""Audit repository - DB operations for the tenant-scoped core audit trail.

``hash`` / ``prev_hash`` are filled by the DB trigger ``core_audit_logs_set_hash``
at INSERT time; the append-only trigger blocks later UPDATE / DELETE. Writes
only - there is no update or delete path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from core.db.repository import SqlRepository
from core.domain.entities import AuditLogEntry
from core.models.core_audit_log import CoreAuditLogModel

if TYPE_CHECKING:
    import uuid


def _audit_from_orm(model: CoreAuditLogModel) -> AuditLogEntry:
    return AuditLogEntry(
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


class AuditLogRepository(SqlRepository):
    """Concrete SQLAlchemy implementation of :class:`AuditLogRepositoryPort`."""

    async def add(self, entry: AuditLogEntry) -> AuditLogEntry:
        """Append one immutable audit event; the trigger computes the chain hashes."""
        model = CoreAuditLogModel(
            tenant_id=entry.tenant_id,
            action=entry.action,
            target=entry.target,
            actor_user_id=entry.actor_user_id,
            details=entry.details,
            ip_address=entry.ip_address,
            user_agent=entry.user_agent,
        )
        if entry.id is not None:
            model.id = entry.id
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _audit_from_orm(model)

    async def list(
        self,
        tenant_id: uuid.UUID,
        *,
        action: str | None = None,
        limit: int = 100,
    ) -> list[AuditLogEntry]:
        """Get audit entries for a tenant, newest first, optionally filtered."""
        stmt = select(CoreAuditLogModel).where(CoreAuditLogModel.tenant_id == tenant_id)
        if action is not None:
            stmt = stmt.where(CoreAuditLogModel.action == action)
        stmt = stmt.order_by(
            CoreAuditLogModel.created_at.desc(), CoreAuditLogModel.id.desc()
        ).limit(limit)
        result = await self.session.execute(stmt)
        return [_audit_from_orm(model) for model in result.scalars().all()]

    async def get(self, tenant_id: uuid.UUID, entry_id: uuid.UUID) -> AuditLogEntry | None:
        stmt = select(CoreAuditLogModel).where(
            CoreAuditLogModel.tenant_id == tenant_id,
            CoreAuditLogModel.id == entry_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _audit_from_orm(model) if model is not None else None
