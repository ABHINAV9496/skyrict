"""Tenant-scoped persistence for L4 what-if scenario snapshots (SKY-93).

Each scenario is a frozen version: the normalized actions and the deterministic
projection are stored together on create.  Reads are served directly from the
stored JSONB - the engine is never re-run.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import desc, select

from ai_agent.models.ai_l4_scenario import AiL4ScenarioModel
from skyrict_common.exceptions import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class L4ScenarioRepository:
    """Persistence for named what-if scenarios."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        scenario_id: uuid.UUID,
        name: str,
        description: str | None,
        base_as_of: date,
        horizon: int,
        currency: str,
        actions: list[dict[str, object]],
        projection: dict[str, object],
        created_by: uuid.UUID,
    ) -> AiL4ScenarioModel:
        """Insert one scenario row."""
        row = AiL4ScenarioModel(
            tenant_id=tenant_id,
            id=scenario_id,
            name=name,
            description=description,
            base_as_of=base_as_of,
            horizon=horizon,
            currency=currency,
            actions=actions,
            projection=projection,
            created_by=created_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_all(self, *, tenant_id: uuid.UUID, limit: int = 100) -> list[AiL4ScenarioModel]:
        """List scenarios for this tenant, newest first."""
        result = await self.session.execute(
            select(AiL4ScenarioModel)
            .where(AiL4ScenarioModel.tenant_id == tenant_id)
            .order_by(desc(AiL4ScenarioModel.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get(self, *, tenant_id: uuid.UUID, scenario_id: uuid.UUID) -> AiL4ScenarioModel:
        """Fetch one scenario; 404 when absent or mis-scoped."""
        result = await self.session.execute(
            select(AiL4ScenarioModel).where(
                AiL4ScenarioModel.tenant_id == tenant_id,
                AiL4ScenarioModel.id == scenario_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError("Scenario not found")
        return row
