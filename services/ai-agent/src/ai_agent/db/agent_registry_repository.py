"""agent_registry access (SKY-63 register system agent).

``agent_registry`` is a global (non-tenant) table listing deployable AI agent
modules. The narrator registers a system agent row on startup so the platform
catalog reflects it; reads happen for the scheduled job to confirm the agent is
enabled. SKY-59 adds :meth:`get_deployable` — the runtime resolves an agent's
module + tool allowlist here before any graph executes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from ai_agent.models.agent_registry import AgentRegistryModel
from skyrict_common.exceptions import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class AgentRegistryRepository:
    """Read/upsert access to the global agent catalog."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_enabled(self, name: str) -> bool:
        result = await self._session.execute(
            select(AgentRegistryModel).where(AgentRegistryModel.name == name)
        )
        row = result.scalars().first()
        return bool(row and row.enabled)

    async def get_deployable(self, name: str) -> AgentRegistryModel:
        """Return an enabled registry row, resolving ``module`` + ``tools``.

        Raises:
            NotFoundError: The agent is not registered or is disabled — a
            disabled agent is rejected before any graph executes.
        """
        result = await self._session.execute(
            select(AgentRegistryModel).where(AgentRegistryModel.name == name)
        )
        row = result.scalars().first()
        if row is None or not row.enabled:
            raise NotFoundError(f"Agent not available: {name}")
        return row

    async def upsert_system_agent(self, name: str, module: str) -> AgentRegistryModel:
        result = await self._session.execute(
            select(AgentRegistryModel).where(AgentRegistryModel.name == name)
        )
        row = result.scalars().first()
        if row is None:
            row = AgentRegistryModel(name=name, module=module, enabled=True)
            self._session.add(row)
            await self._session.flush()
        else:
            row.module = module
            row.enabled = True
            await self._session.flush()
        return row
