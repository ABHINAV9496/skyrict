"""/ai/agents endpoints - run, review and resume orchestrated agents (SKY-59).

Authentication here (verified JWT + tenant cross-check); authorization is a
double gate: the core monolith proxy edge checks ERP permissions before
forwarding, and the runtime re-checks each tool's declared permission against
DB-resolved grants before opening or answering an interrupt.

Invoke starts a graph run under a fresh ``graph_run_id``; the run pauses at a
human-in-the-loop interrupt until a reviewer approves or denies it. Lazy
expiry: a pending interrupt past its 24h window auto-denies on any touch.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.api.v1.schemas.agents import (
    AgentDecisionRequest,
    AgentInvokeRequest,
    AgentRunResponse,
    InterruptListResponse,
    to_interrupt_item,
    to_run_response,
)
from ai_agent.graphs.checkpointer import SqlAlchemyCheckpointSaver
from ai_agent.graphs.runtime import AgentRuntime

router = APIRouter(prefix="/ai/agents", tags=["ai-agents"])


def get_runtime(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AgentRuntime:
    """Compose the runtime for one request (stateless saver per request)."""
    return AgentRuntime(
        session=session,
        checkpointer=SqlAlchemyCheckpointSaver(),
    )


@router.post("/{agent_name}/invoke", response_model=AgentRunResponse)
async def invoke_agent(
    agent_name: str,
    body: AgentInvokeRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> AgentRunResponse:
    """Start one agent run under the caller's resolved grants."""
    outcome = await runtime.invoke(
        agent_name=agent_name,
        input_payload=body.input,
        user_id=user["user_id"],
        tenant_id=user["tenant_id"],
    )
    return to_run_response(outcome)


@router.get("/{agent_name}/interrupts", response_model=InterruptListResponse)
async def list_interrupts(
    agent_name: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> InterruptListResponse:
    """This tenant's pending review queue (oldest expiry first)."""
    rows = await runtime.list_pending(tenant_id=user["tenant_id"])
    return InterruptListResponse(
        data=[to_interrupt_item(r) for r in rows],
        meta={"agent_name": agent_name, "pending": len(rows)},
    )


@router.post(
    "/{agent_name}/interrupts/{interrupt_id}/approve",
    response_model=AgentRunResponse,
)
async def approve_interrupt(
    agent_name: str,
    interrupt_id: uuid.UUID,
    body: AgentDecisionRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> AgentRunResponse:
    """Approve the tool call and resume the paused run."""
    return await _decide(
        runtime=runtime,
        agent_name=agent_name,
        interrupt_id=interrupt_id,
        decision="approved",
        body=body,
        user=user,
    )


@router.post(
    "/{agent_name}/interrupts/{interrupt_id}/deny",
    response_model=AgentRunResponse,
)
async def deny_interrupt(
    agent_name: str,
    interrupt_id: uuid.UUID,
    body: AgentDecisionRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> AgentRunResponse:
    """Deny the tool call and resume the paused run (no-op apply)."""
    return await _decide(
        runtime=runtime,
        agent_name=agent_name,
        interrupt_id=interrupt_id,
        decision="denied",
        body=body,
        user=user,
    )


async def _decide(
    *,
    runtime: AgentRuntime,
    agent_name: str,
    interrupt_id: uuid.UUID,
    decision: Literal["approved", "denied"],
    body: AgentDecisionRequest,
    user: dict[str, Any],
) -> AgentRunResponse:
    outcome = await runtime.resume(
        agent_name=agent_name,
        interrupt_id=interrupt_id,
        decision=decision,
        decided_by=user["user_id"],
        note=body.note,
        user_id=user["user_id"],
        tenant_id=user["tenant_id"],
    )
    return to_run_response(outcome)
