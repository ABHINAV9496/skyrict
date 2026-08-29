"""Tenant-scoped access to ai_restock_demand_stats (INV-AI-002).

The backfill upserts one row per (product, warehouse) on every scan so the
table is always a fresh rolling snapshot; the scan then reads the snapshot
back to compose each suggestion's :class:`DemandStats`. Upsert uses Postgres
``ON CONFLICT DO UPDATE`` - scans are idempotent.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ai_agent.domain.demand_stats import DemandStats
from ai_agent.models.ai_restock_demand_stats import AiRestockDemandStatsModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_ConflictedPair = tuple[uuid.UUID, uuid.UUID]


class RestockStatsRepository:
    """Persistence for the rolling per-SKU demand profile."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, *, tenant_id: uuid.UUID, stats: DemandStats) -> None:
        """Upsert one product+warehouse row; concurrent scans converge."""
        values: dict[str, object] = {
            "tenant_id": tenant_id,
            "product_id": stats.product_id,
            "warehouse_id": stats.warehouse_id,
            "avg_daily_demand": str(stats.avg_daily_demand),
            "demand_cv": str(stats.demand_cv),
            "window_days": stats.window_days,
            "last_receipt_at": stats.last_receipt_at,
            "eligible": stats.eligible,
        }
        insert_stmt = insert(AiRestockDemandStatsModel).values(**values)
        insert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["tenant_id", "product_id", "warehouse_id"],
            set_={
                "avg_daily_demand": insert_stmt.excluded.avg_daily_demand,
                "demand_cv": insert_stmt.excluded.demand_cv,
                "window_days": insert_stmt.excluded.window_days,
                "last_receipt_at": insert_stmt.excluded.last_receipt_at,
                "eligible": insert_stmt.excluded.eligible,
                "computed_at": func.now(),
            },
        )
        await self.session.execute(insert_stmt)

    async def list_all(self, *, tenant_id: uuid.UUID) -> dict[_ConflictedPair, DemandStats]:
        """All demand rows for one tenant, keyed by (product_id, warehouse_id)."""
        result = await self.session.execute(
            select(AiRestockDemandStatsModel).where(
                AiRestockDemandStatsModel.tenant_id == tenant_id
            )
        )
        return {
            (row.product_id, row.warehouse_id): _to_stats(row) for row in result.scalars().all()
        }


def _to_stats(row: AiRestockDemandStatsModel) -> DemandStats:
    return DemandStats(
        product_id=row.product_id,
        warehouse_id=row.warehouse_id,
        avg_daily_demand=row.avg_daily_demand,
        demand_cv=row.demand_cv,
        window_days=row.window_days,
        last_receipt_at=row.last_receipt_at,
        eligible=row.eligible,
    )
