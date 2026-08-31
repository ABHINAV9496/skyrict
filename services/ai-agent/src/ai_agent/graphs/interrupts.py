"""agent_interrupts ledger — create, list, decide, lazy-expire (SKY-59).

Mirrors the ``ai_suggestions`` review flow (db/suggestion_repository.py) but
with LAZY expiry: any read/resume/approval that touches an expired pending row
computes ``denied`` + an audit row right there, so no background sweeper is
required to keep the ledger honest. The 24h window is the model's server
default (``now() + interval '24 hours'``).

The reset-on-touch semantics matter for security: an interrupt can only be
answered through this row (same tenant, same graph_run_id), and a stale
pending row can never outlive its window silently.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import select, update

from ai_agent.models.agent_interrupt import AgentInterruptModel
from skyrict_common.exceptions import ConflictError, NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

Decision = Literal["approved", "denied"]


def _utcnow() -> datetime:
    """Aware-UTC now."""
    return datetime.now(tz=UTC)


class InterruptRepository:
    """Tenant-scoped CRUD over the human-in-the-loop ledger."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_pending(
        self,
        *,
        tenant_id: uuid.UUID,
        graph_run_id: uuid.UUID,
        agent_name: str,
        tool: str,
        payload: dict[str, Any],
    ) -> AgentInterruptModel:
        """Open one pending interrupt for a paused graph run."""
        row = AgentInterruptModel(
            tenant_id=tenant_id,
            id=uuid.uuid4(),
            graph_run_id=graph_run_id,
            agent_name=agent_name,
            tool=tool,
            payload=payload,
            status="pending",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=24),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_pending(
        self, *, tenant_id: uuid.UUID, limit: int = 100
    ) -> list[AgentInterruptModel]:
        """Pending rows (oldest expiry first) — the review queue order."""
        result = await self._session.execute(
            select(AgentInterruptModel)
            .where(
                AgentInterruptModel.tenant_id == tenant_id,
                AgentInterruptModel.status == "pending",
            )
            .order_by(AgentInterruptModel.expires_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_for_decision(
        self, *, tenant_id: uuid.UUID, interrupt_id: uuid.UUID
    ) -> AgentInterruptModel:
        """Fetch one row for review; 404 when absent or mis-scoped."""
        result = await self._session.execute(
            select(AgentInterruptModel).where(
                AgentInterruptModel.tenant_id == tenant_id,
                AgentInterruptModel.id == interrupt_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError("Interrupt not found")
        return row

    async def expire_if_stale(self, row: AgentInterruptModel) -> bool:
        """Lazily auto-deny a pending row past its window (SKY-59, 24h).

        Returns True when a transition to ``denied`` was just computed; the
        caller then audits ``ai.agent.interrupt.expired``. ``decided_by`` stays
        NULL — no human decided; the clock did.
        """
        if row.status != "pending" or row.expires_at > _utcnow():
            return False
        await self.record_decision(row, decision="denied", decided_by=None)
        return True

    async def record_decision(
        self,
        row: AgentInterruptModel,
        *,
        decision: Decision,
        decided_by: uuid.UUID | None,
    ) -> AgentInterruptModel:
        """Apply a review decision; refuses non-pending transitions."""
        if row.status != "pending":
            raise ConflictError(f"Interrupt already decided: {row.status}")
        now = _utcnow()
        result = await self._session.execute(
            update(AgentInterruptModel)
            .where(
                AgentInterruptModel.tenant_id == row.tenant_id,
                AgentInterruptModel.id == row.id,
                AgentInterruptModel.status == "pending",
            )
            .values(status=decision, decided_by=decided_by, decided_at=now)
        )
        if not (result.rowcount or 0):  # type: ignore[attr-defined]
            raise ConflictError("Interrupt already decided")
        row.status = decision
        row.decided_by = decided_by
        row.decided_at = now
        await self._session.flush()
        return row
