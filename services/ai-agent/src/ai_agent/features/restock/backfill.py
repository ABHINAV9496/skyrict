"""Restock demand-profile backfill (INV-AI-002, spec §3.2).

Runs inside the restock scan before suggestion drafts are computed: for every
product+warehouse pair in the stock catalog it derives rolling demand stats
from the already-fetched movement window (see :mod:`demand_stats`), upserts
them into ``ai_restock_demand_stats``, and returns the in-memory map the scan
uses to feed the v2 formula. ``eligible`` pairs graduate to the enhanced
formula; the rest stay on the v1 heuristic.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from ai_agent.db.restock_stats_repository import RestockStatsRepository
    from ai_agent.features.nl_query.gateway import MovementRow, StockLevelRow

from ai_agent.domain.demand_stats import DemandStats
from ai_agent.features.restock.demand_stats import compute_demand_stats

logger = structlog.get_logger("ai_agent.restock_backfill")

_DemandMap = dict[tuple[uuid.UUID, uuid.UUID], DemandStats]


class BackfillService:
    """Compute + persist one tenant's rolling demand profile."""

    def __init__(self, *, stats: RestockStatsRepository) -> None:
        self._stats = stats

    async def backfill_and_load(
        self,
        *,
        tenant_id: uuid.UUID,
        levels: list[StockLevelRow],
        movements: list[MovementRow],
    ) -> _DemandMap:
        pairs = {(row.product_id, row.warehouse_id) for row in levels}
        profile = {
            pair: compute_demand_stats(
                product_id=pair[0],
                warehouse_id=pair[1],
                movements=movements,
            )
            for pair in pairs
        }
        for stats in profile.values():
            await self._stats.upsert(tenant_id=tenant_id, stats=stats)
        logger.info(
            "restock_backfill.completed",
            pairs=len(profile),
            eligible=sum(1 for s in profile.values() if s.eligible),
        )
        return profile
