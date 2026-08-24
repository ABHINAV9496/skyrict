"""Repository for the append-only ``ai_audit_log`` table.

The single write path for AI audit rows. There is deliberately no update or
delete method - the audit trail is insert-only (see the model docstring);
reads happen through the feature repositories that own their tables.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from ai_agent.models.ai_audit_log import AiAuditLogModel

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


class AiAuditLogRepository:
    """Append audit rows and read a tenant's newest-first trail."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        user_id: uuid.UUID | None = None,
        input_payload: dict[str, Any] | None = None,
        output_payload: dict[str, Any] | None = None,
        model_used: str | None = None,
        latency_ms: int | None = None,
    ) -> AiAuditLogModel:
        """Insert one immutable audit event (committed with the unit of work)."""
        row = AiAuditLogModel(
            tenant_id=tenant_id,
            action=action,
            user_id=user_id,
            input=input_payload,
            output=output_payload,
            model_used=model_used,
            latency_ms=latency_ms,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        limit: int = 100,
    ) -> list[AiAuditLogModel]:
        """Return the tenant's trail, newest first (RLS scopes the query)."""
        result = await self._session.execute(
            select(AiAuditLogModel)
            .where(AiAuditLogModel.tenant_id == tenant_id)
            .order_by(AiAuditLogModel.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
