"""Inventory embedding snapshot writer (SKY-70) — feature layer.

Builds and persists the per-product semantic snapshot that hybrid search
reads. Two write surfaces share this service:

- post-commit sync: core dispatches ``inventory.product.upserted`` /
  ``.removed`` envelopes to ``POST /ai/inventory/embeddings/sync`` (a small,
  frequent batch of changed products);
- ``inventory reindex`` CLI: an operator-driven full/partial rebuild pulled
  from core's catalog.

``build_embedding_text`` reproduces exactly the string migration 0012 embeds
(``"{sku} {name} {category} {unit}"``, no glue tokens) so sync and reindex
produce identical vectors for the same product.

Degradation contract mirrors search: removes apply even when no embedding
provider is configured (they need no vectors), while a missing/failed
provider skips upserts and reports ``skipped=True`` instead of erroring —
the core dispatch is best-effort by design. The reindex CLI is stricter and
requires a provider before it starts (see ``ai_agent/inventory_reindex.py``).

Layering (import-linter "feature layer, no models/db"): the store is a
protocol implemented by the DB repository, injected at the composition roots.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import structlog

if TYPE_CHECKING:
    import uuid

    from ai_agent.core.embedding import EmbeddingProvider

logger = structlog.get_logger("ai_agent.inventory_snapshot")


@dataclass(frozen=True, slots=True)
class ProductSnapshot:
    """One product's searchable catalog text — never money or PII (spec §5.5)."""

    product_id: uuid.UUID
    sku: str
    name: str
    category: str | None = None
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class InventorySnapshotReport:
    """Outcome of one sync/reindex apply for audit + logging."""

    upserts_applied: int
    removes_applied: int
    skipped: bool
    model_used: str | None
    dims: int | None


class InventorySnapshotStore(Protocol):
    """Write contract implemented by db/inventory_embedding_repository."""

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
    ) -> None: ...

    async def delete(
        self,
        *,
        tenant_id: uuid.UUID,
        product_id: uuid.UUID,
    ) -> None: ...


class InventorySnapshotSyncService:
    """Embeds and persists product snapshot rows for one tenant.

    Args:
        embedding_provider: Embedded text source; None degrades to removes-only.
        store: Snapshot persistence (repository), pre-scoped to the tenant by
            the composition root (RLS + explicit tenant_id arguments).
    """

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider | None,
        store: InventorySnapshotStore,
    ) -> None:
        self._embedding_provider = embedding_provider
        self._store = store

    async def apply(
        self,
        *,
        tenant_id: uuid.UUID,
        upserts: list[ProductSnapshot],
        removes: list[uuid.UUID],
    ) -> InventorySnapshotReport:
        """Apply one batch: deletes first (never choked by an embed failure)."""
        for product_id in removes:
            await self._store.delete(tenant_id=tenant_id, product_id=product_id)

        provider = self._embedding_provider
        if provider is None:
            if upserts:
                logger.warning(
                    "inventory_snapshot.upserts_skipped",
                    tenant_id=str(tenant_id),
                    reason="no embedding provider configured",
                    count=len(upserts),
                )
            return InventorySnapshotReport(
                upserts_applied=0,
                removes_applied=len(removes),
                skipped=bool(upserts),
                model_used=None,
                dims=None,
            )

        if not upserts:
            return InventorySnapshotReport(
                upserts_applied=0,
                removes_applied=len(removes),
                skipped=False,
                model_used=None,
                dims=None,
            )

        texts = [
            build_embedding_text(
                sku=product.sku,
                name=product.name,
                category=product.category,
                unit=product.unit,
            )
            for product in upserts
        ]
        embedded = await provider.embed(texts)
        for product, vector in zip(upserts, embedded.vectors, strict=True):
            await self._store.upsert(
                tenant_id=tenant_id,
                product_id=product.product_id,
                sku=product.sku,
                name=product.name,
                category=product.category,
                unit=product.unit,
                embedding=vector,
                embedding_model=embedded.model_used,
                dims=embedded.dims,
            )
        return InventorySnapshotReport(
            upserts_applied=len(upserts),
            removes_applied=len(removes),
            skipped=False,
            model_used=embedded.model_used,
            dims=embedded.dims,
        )


def build_embedding_text(
    *,
    sku: str,
    name: str,
    category: str | None = None,
    unit: str | None = None,
) -> str:
    """Concatenate the existing catalog text exactly as migration 0012 documents.

    ``"{sku} {name} {category} {unit}"`` with empty/None parts dropped — the
    identical string embedded at every write so vectors stay reproducible.
    """
    return " ".join(part for part in (sku, name, category, unit) if part)
