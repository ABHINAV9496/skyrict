"""Persistence for ai_query_cache — the cold layer of the two-tier RAG cache.

Redis is the hot path (sub-50ms identical queries); this table is the durable
layer: it records the normalized query text, hash, and JSON response with a
1-hour expiry, and keeps a hit counter for analytics. The write-through path
upserts on the tenant-scoped unique ``(tenant_id, query_hash)`` index — a
second identical query from the SAME tenant increments ``hit_count`` instead
of inserting a duplicate row (migration 0003 fixed 0002's global-unique bug
so this conflict target exists).

Expired rows are left in place for the hourly cleanup sweep (deferred to the
RAGAS/nightly commit, same pattern as ai_episodic_memory). Reads are not
serve-from-DB: a Redis miss falls through to a fresh retrieval, then writes
through BOTH layers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ai_agent.models.ai_query_cache import AiQueryCacheModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class QueryCacheRepository:
    """Tenant-scoped write-through persistence for RAG query responses."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def put(
        self,
        *,
        tenant_id: uuid.UUID,
        query_hash: str,
        query_text: str,
        response: dict[str, object],
        ttl_seconds: int,
    ) -> None:
        """Upsert one cache entry; a same-hash repeat increments hit_count."""
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        stmt = (
            insert(AiQueryCacheModel)
            .values(
                tenant_id=tenant_id,
                id=uuid.uuid4(),
                query_hash=query_hash,
                query_text=query_text,
                response=response,
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                constraint="uq_ai_query_cache_tenant_hash",
                set_={
                    "response": response,
                    "expires_at": expires_at,
                    "hit_count": AiQueryCacheModel.hit_count + 1,
                },
            )
        )
        await self.session.execute(stmt)

    async def get(self, *, tenant_id: uuid.UUID, query_hash: str) -> AiQueryCacheModel | None:
        """Return the live cache row, if any (unexpired entries only)."""
        result = await self.session.execute(
            select(AiQueryCacheModel).where(
                AiQueryCacheModel.tenant_id == tenant_id,
                AiQueryCacheModel.query_hash == query_hash,
                AiQueryCacheModel.expires_at > func.now(),
            )
        )
        return result.scalar_one_or_none()
