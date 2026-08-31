"""Agent orchestration API schemas (SKY-59)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

RunStatus = Literal["completed", "awaiting_decision", "failed"]


class AgentInvokeRequest(BaseModel):
    """The agent's input state; validated by the graph's node contracts."""

    input: dict[str, Any] = Field(default_factory=dict)


class InterruptItem(BaseModel):
    """One human-in-the-loop ledger row, as shown in the review queue."""

    id: uuid.UUID
    graph_run_id: uuid.UUID
    agent_name: str
    tool: str
    payload: dict[str, Any]
    status: Literal["pending", "approved", "denied"]
    expires_at: datetime
    created_at: datetime
    decided_by: uuid.UUID | None = None
    decided_at: datetime | None = None


class AgentRunResponse(BaseModel):
    """The result of an invoke/resume step for one graph run."""

    graph_run_id: uuid.UUID
    agent_name: str
    status: RunStatus
    output: dict[str, Any] | None = None
    interrupt: InterruptItem | None = None


class AgentDecisionRequest(BaseModel):
    """Free-text note captured with an approve/deny decision."""

    note: str | None = Field(default=None, max_length=1000)


class InterruptListResponse(BaseModel):
    data: list[InterruptItem]
    meta: dict[str, Any]


def to_interrupt_item(row: Any) -> InterruptItem:
    """Map a ledger row (or fake) to the review schema."""
    return InterruptItem(
        id=row.id,
        graph_run_id=row.graph_run_id,
        agent_name=row.agent_name,
        tool=row.tool,
        payload=row.payload,
        status=row.status,
        expires_at=row.expires_at,
        created_at=row.created_at,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
    )


def to_run_response(outcome: Any) -> AgentRunResponse:
    """Map a runtime outcome to the API schema."""
    interrupt = to_interrupt_item(outcome.interrupt) if outcome.interrupt is not None else None
    return AgentRunResponse(
        graph_run_id=outcome.graph_run_id,
        agent_name=outcome.agent_name,
        status=outcome.status,
        output=outcome.output,
        interrupt=interrupt,
    )
