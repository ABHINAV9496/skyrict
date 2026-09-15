"""Memory repository - CRUD for episodic and semantic memory.

Handles storing and retrieving conversation memories for the CRM Assistant.
Episodic memories are full query-response pairs; semantic memories are
extracted facts. Both auto-expire after 90 days.

Compaction (SKY-90): the weekly compaction job summarizes older episodic
rows into semantic facts and stamps ``compacted_at`` on them. Compacted
rows are excluded from recall - their essence survives as semantic facts,
which keeps the recall context budget bounded.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import delete, select, text, update

from ai_agent.models.ai_episodic_memory import AiEpisodicMemoryModel
from ai_agent.models.ai_semantic_memory import AiSemanticMemoryModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("ai_agent.memory_repo")

# How many recent episodic memories to include in context recall.
_EPISODIC_LIMIT = 5
# How many semantic facts to include in context recall.
_SEMANTIC_LIMIT = 10


class MemoryRepository:
    """Tenant-scoped read/write for episodic and semantic memory."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Episodic memory
    # ------------------------------------------------------------------

    async def store_episodic(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        query_text: str,
        response_summary: str,
        module: str | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        embedding: list[float] | None = None,
        embedding_model: str | None = None,
    ) -> AiEpisodicMemoryModel:
        """Persist one query-response pair.

        ``embedding``/``embedding_model`` are written only when the caller has
        an embedding provider (SKY-100); NULL keeps the row on the
        trigram/recency recall path.
        """
        now = datetime.now(UTC)
        row = AiEpisodicMemoryModel(
            tenant_id=tenant_id,
            id=uuid.uuid4(),
            user_id=user_id,
            query_text=query_text,
            response_summary=response_summary,
            module=module,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            created_at=now,
            expires_at=now + timedelta(days=90),
            compacted_at=None,
            embedding=embedding,
            embedding_model=embedding_model,
            embedding_dims=len(embedding) if embedding else None,
        )
        self._session.add(row)
        await self._session.flush()
        logger.info(
            "memory.episodic_stored",
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            module=module,
        )
        return row

    async def recall_episodic(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        query: str,
        limit: int = _EPISODIC_LIMIT,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve the most relevant, not-yet-compacted episodic memories.

        Ranked by cosine similarity over embedded rows when the caller
        supplies ``query_embedding`` (SKY-100); falls back to trigram
        similarity on query_text, then to most-recent, when embeddings are
        absent or unavailable. Compacted rows are excluded (SKY-90) - their
        essence lives in semantic memory.
        """
        now = datetime.now(UTC)
        if query_embedding is not None:
            try:
                result = await self._session.execute(
                    select(
                        AiEpisodicMemoryModel.query_text,
                        AiEpisodicMemoryModel.response_summary,
                        AiEpisodicMemoryModel.created_at,
                    )
                    .where(
                        AiEpisodicMemoryModel.tenant_id == tenant_id,
                        AiEpisodicMemoryModel.user_id == user_id,
                        AiEpisodicMemoryModel.expires_at > now,
                        AiEpisodicMemoryModel.compacted_at.is_(None),
                        AiEpisodicMemoryModel.embedding.is_not(None),
                    )
                    .order_by(AiEpisodicMemoryModel.embedding.cosine_distance(query_embedding))
                    .limit(limit)
                )
                cosine_rows = [
                    {
                        "query": r.query_text,
                        "summary": r.response_summary,
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in result.all()
                ]
                if cosine_rows:
                    return cosine_rows
            except Exception:
                pass  # pgvector unavailable - fall through to trigram/recency.
        # Fallback: trigram then recency when cosine is absent, empty, or failed.
        try:
            result = await self._session.execute(
                select(
                    AiEpisodicMemoryModel.query_text,
                    AiEpisodicMemoryModel.response_summary,
                    AiEpisodicMemoryModel.created_at,
                    text("similarity(query_text, :query) AS sim"),
                )
                .where(
                    AiEpisodicMemoryModel.tenant_id == tenant_id,
                    AiEpisodicMemoryModel.user_id == user_id,
                    AiEpisodicMemoryModel.expires_at > now,
                    AiEpisodicMemoryModel.compacted_at.is_(None),
                )
                .order_by(text("sim DESC"))
                .limit(limit)
                .params(query=query)
            )
            rows = result.all()
            if rows:
                return [
                    {
                        "query": r.query_text,
                        "summary": r.response_summary,
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in rows
                ]
        except Exception:
            pass  # pg_trgm not available - fall through to recency.

        # Fallback: most recent not-yet-compacted.
        result = await self._session.execute(
            select(AiEpisodicMemoryModel)
            .where(
                AiEpisodicMemoryModel.tenant_id == tenant_id,
                AiEpisodicMemoryModel.user_id == user_id,
                AiEpisodicMemoryModel.expires_at > now,
                AiEpisodicMemoryModel.compacted_at.is_(None),
            )
            .order_by(AiEpisodicMemoryModel.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "query": r.query_text,
                "summary": r.response_summary,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]

    async def list_uncompacted_episodic(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        before: datetime,
        limit: int = 100,
    ) -> list[AiEpisodicMemoryModel]:
        """Rows older than ``before`` that the compaction job has not folded.

        The compaction batch for one user - oldest first so the job always
        folds the same content in one pass and marks it before re-reading.
        """
        result = await self._session.execute(
            select(AiEpisodicMemoryModel)
            .where(
                AiEpisodicMemoryModel.tenant_id == tenant_id,
                AiEpisodicMemoryModel.user_id == user_id,
                AiEpisodicMemoryModel.expires_at > datetime.now(UTC),
                AiEpisodicMemoryModel.compacted_at.is_(None),
                AiEpisodicMemoryModel.created_at < before,
            )
            .order_by(AiEpisodicMemoryModel.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_users_with_uncompacted_episodic(
        self,
        *,
        tenant_id: uuid.UUID,
        before: datetime,
    ) -> list[uuid.UUID]:
        """Distinct users holding uncompacted, unexpired rows older than ``before``.

        The compaction scheduler enumerates the per-tenant work set with this
        query instead of iterating the platform user directory - episodic rows
        are the only source of truth for who actually has a pending fold.
        """
        result = await self._session.execute(
            select(AiEpisodicMemoryModel.user_id)
            .where(
                AiEpisodicMemoryModel.tenant_id == tenant_id,
                AiEpisodicMemoryModel.expires_at > datetime.now(UTC),
                AiEpisodicMemoryModel.compacted_at.is_(None),
                AiEpisodicMemoryModel.created_at < before,
            )
            .distinct()
            .order_by(AiEpisodicMemoryModel.user_id)
        )
        return list(result.scalars().all())

    async def mark_episodic_compacted(
        self,
        *,
        tenant_id: uuid.UUID,
        ids: list[uuid.UUID],
    ) -> int:
        """Stamp ``compacted_at`` on the given rows; returns rowcount."""
        if not ids:
            return 0
        result = await self._session.execute(
            update(AiEpisodicMemoryModel)
            .where(
                AiEpisodicMemoryModel.tenant_id == tenant_id,
                AiEpisodicMemoryModel.id.in_(ids),
            )
            .values(compacted_at=datetime.now(UTC))
        )
        await self._session.flush()
        return result.rowcount or 0  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Semantic memory
    # ------------------------------------------------------------------

    async def store_semantic_facts(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        facts: list[dict[str, Any]],
        embeddings: list[list[float]] | None = None,
        embedding_model: str | None = None,
    ) -> list[AiSemanticMemoryModel]:
        """Persist extracted facts. Each dict must have 'fact' and 'category'.

        ``embeddings`` are written when the caller has an embedding provider
        (SKY-100); NULL keeps the fact on the trigram/recency recall path.
        """
        now = datetime.now(UTC)
        rows = []
        for idx, fact_data in enumerate(facts):
            embedding = embeddings[idx] if embeddings and idx < len(embeddings) else None
            row = AiSemanticMemoryModel(
                tenant_id=tenant_id,
                id=uuid.uuid4(),
                user_id=user_id,
                fact=str(fact_data.get("fact", "")),
                category=str(fact_data.get("category", "context")),
                entity_type=fact_data.get("entity_type"),
                entity_id=fact_data.get("entity_id"),
                confidence=float(fact_data.get("confidence", 0.8)),
                source=str(fact_data.get("source", "conversation")),
                created_at=now,
                expires_at=now + timedelta(days=90),
                embedding=embedding,
                embedding_model=embedding_model if embedding else None,
                embedding_dims=len(embedding) if embedding else None,
            )
            self._session.add(row)
            rows.append(row)
        await self._session.flush()
        logger.info(
            "memory.semantic_stored",
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            count=len(rows),
        )
        return rows

    async def recall_semantic(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        query: str,
        limit: int = _SEMANTIC_LIMIT,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve semantic facts relevant to the current query.

        Ranked by cosine similarity when the caller supplies
        ``query_embedding`` (SKY-100); falls back to trigram then to
        recency when embeddings are absent or unavailable.
        """
        now = datetime.now(UTC)
        if query_embedding is not None:
            try:
                result = await self._session.execute(
                    select(
                        AiSemanticMemoryModel.fact,
                        AiSemanticMemoryModel.category,
                        AiSemanticMemoryModel.confidence,
                        AiSemanticMemoryModel.entity_type,
                    )
                    .where(
                        AiSemanticMemoryModel.tenant_id == tenant_id,
                        AiSemanticMemoryModel.user_id == user_id,
                        AiSemanticMemoryModel.expires_at > now,
                        AiSemanticMemoryModel.embedding.is_not(None),
                    )
                    .order_by(AiSemanticMemoryModel.embedding.cosine_distance(query_embedding))
                    .limit(limit)
                )
                cosine_rows = [
                    {
                        "fact": r.fact,
                        "category": r.category,
                        "confidence": r.confidence,
                        "entity_type": r.entity_type,
                    }
                    for r in result.all()
                ]
                if cosine_rows:
                    return cosine_rows
            except Exception:
                pass  # pgvector unavailable - fall through to trigram/recency.
        try:
            result = await self._session.execute(
                select(
                    AiSemanticMemoryModel.fact,
                    AiSemanticMemoryModel.category,
                    AiSemanticMemoryModel.confidence,
                    AiSemanticMemoryModel.entity_type,
                    text("similarity(fact, :query) AS sim"),
                )
                .where(
                    AiSemanticMemoryModel.tenant_id == tenant_id,
                    AiSemanticMemoryModel.user_id == user_id,
                    AiSemanticMemoryModel.expires_at > now,
                )
                .order_by(text("sim DESC"))
                .limit(limit)
                .params(query=query)
            )
            rows = result.all()
            if rows:
                return [
                    {
                        "fact": r.fact,
                        "category": r.category,
                        "confidence": r.confidence,
                        "entity_type": r.entity_type,
                    }
                    for r in rows
                ]
        except Exception:
            pass

        # Fallback: most recent by category.
        result = await self._session.execute(
            select(AiSemanticMemoryModel)
            .where(
                AiSemanticMemoryModel.tenant_id == tenant_id,
                AiSemanticMemoryModel.user_id == user_id,
                AiSemanticMemoryModel.expires_at > now,
            )
            .order_by(AiSemanticMemoryModel.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "fact": r.fact,
                "category": r.category,
                "confidence": r.confidence,
                "entity_type": r.entity_type,
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def delete_expired(self, *, tenant_id: uuid.UUID) -> int:
        """Remove expired episodic and semantic memories. Returns total deleted."""
        now = datetime.now(UTC)
        episodic = await self._session.execute(
            delete(AiEpisodicMemoryModel).where(
                AiEpisodicMemoryModel.tenant_id == tenant_id,
                AiEpisodicMemoryModel.expires_at <= now,
            )
        )
        semantic = await self._session.execute(
            delete(AiSemanticMemoryModel).where(
                AiSemanticMemoryModel.tenant_id == tenant_id,
                AiSemanticMemoryModel.expires_at <= now,
            )
        )
        total = (episodic.rowcount or 0) + (semantic.rowcount or 0)  # type: ignore[attr-defined]
        if total > 0:
            logger.info(
                "memory.expired_deleted",
                tenant_id=str(tenant_id),
                episodic=episodic.rowcount,  # type: ignore[attr-defined]
                semantic=semantic.rowcount,  # type: ignore[attr-defined]
            )
        return total
