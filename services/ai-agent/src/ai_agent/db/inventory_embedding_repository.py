"""Persistence for the per-product semantic embedding snapshot (SKY-70).

One row per ``(tenant_id, product_id)`` holds the concatenated catalog text
(sku, name, category, unit) and its 768-dim embedding. ``upsert`` /
``delete`` are idempotent (post-commit HTTP sync and the ``inventory
reindex`` CLI must both be safe to re-run), and index writes NEVER go down
the 404 hot path — search reads via ``semantic_search`` while the write
surface lives on the sync endpoint and CLI.

RLS bounds every row to the current session tenant; the caller must populate
:class:`ai_agent.core.tenant.TenantContext` (session GUC) before writing, or
the writes silently match no rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ai_agent.models.ai_inv_item_embedding import AiInvItemEmbeddingModel

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class InventoryExactHit:
    """One product row matched by substring (ILIKE) over the snapshot text."""

    product_id: uuid.UUID
    sku: str
    name: str
    category: str | None
    unit: str | None


@dataclass(frozen=True, slots=True)
class InventoryEmbeddingHit:
    """One product row retrieved by vector similarity."""

    product_id: uuid.UUID
    sku: str
    name: str
    category: str | None
    unit: str | None
    cosine_distance: float
    embedding_model: str


class InventoryEmbeddingRepository:
    """Tenant-scoped access to the per-product embedding snapshot."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        *,
        tenant_id: uuid.UUID,
        product_id: uuid.UUID,
        sku: str,
        name: str,
        category: str | None,
        unit: str | None,
        embedding: list[float],
        embedding_model: str,
        dims: int,
    ) -> None:
        """Insert or replace one product's embedding row (idempotent)."""
        if len(embedding) != dims:
            raise ValueError(f"vector dimension {len(embedding)} != expected {dims}")
        stmt = pg_insert(AiInvItemEmbeddingModel).values(
            tenant_id=tenant_id,
            product_id=product_id,
            sku=sku,
            name=name,
            category=category,
            unit=unit,
            embedding=embedding,
            embedding_model=embedding_model,
            embedding_dims=dims,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                AiInvItemEmbeddingModel.tenant_id,
                AiInvItemEmbeddingModel.product_id,
            ],
            set_={
                "sku": sku,
                "name": name,
                "category": category,
                "unit": unit,
                "embedding": embedding,
                "embedding_model": embedding_model,
                "embedding_dims": dims,
            },
        )
        await self.session.execute(stmt)

    async def delete(
        self,
        *,
        tenant_id: uuid.UUID,
        product_id: uuid.UUID,
    ) -> None:
        """Remove one product's embedding row (idempotent)."""
        await self.session.execute(
            delete(AiInvItemEmbeddingModel).where(
                AiInvItemEmbeddingModel.tenant_id == tenant_id,
                AiInvItemEmbeddingModel.product_id == product_id,
            )
        )

    async def delete_all(self, *, tenant_id: uuid.UUID) -> None:
        """Wipe the tenant's snapshot (used by ``inventory reindex --full``)."""
        await self.session.execute(
            delete(AiInvItemEmbeddingModel).where(AiInvItemEmbeddingModel.tenant_id == tenant_id)
        )

    async def exact_search(
        self,
        *,
        tenant_id: uuid.UUID,
        terms: list[str],
        limit: int,
    ) -> list[InventoryExactHit]:
        """Substring (ILIKE) search over sku/name/category/unit.

        The snapshot carries the same raw strings core serves, so exact
        matching here equals exact matching against the catalog — without a
        second HTTP round trip to core. Row matches ANY term; per-field
        attribution (``matched_fields``) is computed by the service so the
        same tokenization drives both the SQL and the payload.
        """
        if not terms:
            return []
        searchable = (
            func.lower(func.coalesce(AiInvItemEmbeddingModel.sku, "")),
            func.lower(func.coalesce(AiInvItemEmbeddingModel.name, "")),
            func.lower(func.coalesce(AiInvItemEmbeddingModel.category, "")),
            func.lower(func.coalesce(AiInvItemEmbeddingModel.unit, "")),
        )
        conditions = [field.contains(term) for field in searchable for term in terms]
        result = await self.session.execute(
            select(AiInvItemEmbeddingModel)
            .where(AiInvItemEmbeddingModel.tenant_id == tenant_id, or_(*conditions))
            .order_by(AiInvItemEmbeddingModel.sku)
            .limit(limit)
        )
        return [
            InventoryExactHit(
                product_id=row.product_id,
                sku=row.sku,
                name=row.name,
                category=row.category,
                unit=row.unit,
            )
            for row in result.scalars().all()
        ]

    async def semantic_search(
        self,
        *,
        tenant_id: uuid.UUID,
        query_vector: list[float],
        top_k: int,
    ) -> list[InventoryEmbeddingHit]:
        """Cosine-similarity search over product embeddings (ivfflat)."""
        distance = AiInvItemEmbeddingModel.embedding.cosine_distance(query_vector)
        stmt = (
            select(AiInvItemEmbeddingModel, distance)
            .where(AiInvItemEmbeddingModel.tenant_id == tenant_id)
            .order_by(distance)
            .limit(top_k)
        )
        result = await self.session.execute(stmt)
        return [
            InventoryEmbeddingHit(
                product_id=row.product_id,
                sku=row.sku,
                name=row.name,
                category=row.category,
                unit=row.unit,
                cosine_distance=float(distance_value),
                embedding_model=row.embedding_model,
            )
            for row, distance_value in result.all()
        ]
