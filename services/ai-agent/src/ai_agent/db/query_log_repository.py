"""Append-only persistence for ai_query_log (spec §2.6).

One repository, two paths: ``add`` records every executed query; the rest are
tenant-scoped reads for the /ai/query/history endpoint. There is no update or
delete - history rows are immutable facts about what was asked.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import desc, select

from ai_agent.models.ai_query_log import AiQueryLogModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class QueryLogRepository:
    """Tenant-scoped access to the natural-language query log."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        query_text: str,
        parsed_intent: dict[str, object] | None,
        result_summary: str | None,
        model_used: str | None,
        latency_ms: int | None,
    ) -> AiQueryLogModel:
        """Insert one immutable query-log row (committed with the unit of work)."""
        row = AiQueryLogModel(
            tenant_id=tenant_id,
            id=uuid.uuid4(),
            user_id=user_id,
            query_text=query_text,
            parsed_intent=parsed_intent,
            result_summary=result_summary,
            model_used=model_used,
            latency_ms=latency_ms,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for_tenant(
        self, *, tenant_id: uuid.UUID, limit: int = 20
    ) -> list[dict[str, object]]:
        """Newest-first history entries for one tenant."""
        result = await self.session.execute(
            select(AiQueryLogModel)
            .where(AiQueryLogModel.tenant_id == tenant_id)
            .order_by(desc(AiQueryLogModel.created_at))
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "id": row.id,
                "user_id": row.user_id,
                "query_text": row.query_text,
                "result_summary": row.result_summary,
                "model_used": row.model_used,
                "latency_ms": row.latency_ms,
                "created_at": row.created_at,
            }
            for row in rows
        ]
