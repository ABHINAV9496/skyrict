"""Persistence for validated digest snapshots (SKY-63).

``ai_digest_snapshots`` is append-per-generation; "cache" is a derived view
(the newest row for a tenant + ``as_of`` date). The repository exposes the
write path, the latest-for-date read, and the freshness rule the service uses
to decide whether to reuse a cached digest instead of regenerating.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

from ai_agent.models.ai_digest import AiDigestModel

if TYPE_CHECKING:
    from datetime import date, datetime

    from sqlalchemy.ext.asyncio import AsyncSession


class DigestCacheRepository:
    """Tenant-scoped access to cross-module narrator snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(
        self,
        *,
        tenant_id: uuid.UUID,
        status: str,
        as_of: date,
        title: str | None,
        summary: str | None,
        points: list[str] | None,
        caveat: str | None,
        signals: dict[str, object] | None,
        model_used: str | None,
        latency_ms: int | None,
        generated_at: datetime,
    ) -> AiDigestModel:
        row = AiDigestModel(
            tenant_id=tenant_id,
            id=uuid.uuid4(),
            status=status,
            as_of=as_of,
            title=title,
            summary=summary,
            points=points,
            caveat=caveat,
            signals=signals,
            model_used=model_used,
            latency_ms=latency_ms,
            generated_at=generated_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def latest_for_date(self, tenant_id: uuid.UUID, as_of: date) -> AiDigestModel | None:
        """Newest snapshot for a tenant on a given date (cache lookup)."""
        result = await self._session.execute(
            select(AiDigestModel)
            .where(
                AiDigestModel.tenant_id == tenant_id,
                AiDigestModel.as_of == as_of,
            )
            .order_by(AiDigestModel.generated_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    @staticmethod
    def is_fresh_for(row: AiDigestModel, as_of: date) -> bool:
        """A row is fresh when it was produced for the same calendar date."""
        return row.as_of == as_of
