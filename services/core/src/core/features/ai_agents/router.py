"""``/api/v1/ai/agents/*`` proxy routes - permission checks BEFORE forwarding.

SKY-59 agent orchestration runs on ai-agent; the monolith edge enforces the
ERP matrix (spec 6.3, same posture as features/ai/router.py):

  invoke / list queue    erp.ai.invoke
  approve / deny         erp.ai.invoke + erp.finance.write
  chat stream            erp.ai.invoke

The decision edge demands the finance-writer grant because it is a
financial-class write (recorded Q&A decision) - defense in depth on top of
the ai-agent runtime's own tool-permission checks.

The JWT is forwarded verbatim; ai-agent re-verifies it against the relayed
tenant slug (spec 1.4: AI is a proxy, not an auth bypass). Interrupt ids are
typed ``uuid.UUID`` so FastAPI rejects anything else with 422 before the
handler runs; ``agent_name`` is a single path segment (no traversal can be
embedded), and the runtime looks it up exactly in the agent registry.

The supervisor chat stream (SKY-60) relays the SSE body chunk-by-chunk so
the shell renders tokens live; a client disconnect closes the upstream
connection, cancelling the ai-agent LLM stream (see core/features/ai/proxy).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from core.api.deps import require_all_permissions, require_permission
from core.core.permissions import ERP_AI_INVOKE, ERP_FINANCE_WRITE
from core.core.tenant_resolver import derive_tenant_slug
from core.features.ai.proxy import (
    forward_to_ai_agent,
    relay_response,
    relay_stream_response,
)

router = APIRouter(prefix="/ai/agents", tags=["ai-agents"])

_require_ai_invoke = require_permission(ERP_AI_INVOKE)
_require_agent_decision = require_all_permissions(ERP_AI_INVOKE, ERP_FINANCE_WRITE)

_InvokeDep = Annotated[dict[str, Any], Depends(_require_ai_invoke)]
_DecisionDep = Annotated[dict[str, Any], Depends(_require_agent_decision)]


def get_ai_client(request: Request) -> httpx.AsyncClient:
    """The lifespan-owned pooled client to ai-agent (never per-request)."""
    client: httpx.AsyncClient | None = getattr(request.app.state, "ai_client", None)
    if client is None:
        raise RuntimeError("AI agent HTTP client is not initialised")
    return client


_ClientDep = Annotated[httpx.AsyncClient, Depends(get_ai_client)]


async def _proxy(
    request: Request,
    client: httpx.AsyncClient,
    upstream_path: str,
) -> Response:
    """Forward one request after auth+authz deps have already passed."""
    authorization = request.headers.get("authorization")
    body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None
    upstream = await forward_to_ai_agent(
        client,
        method=request.method,
        upstream_path=upstream_path,
        authorization=authorization,
        tenant_slug=derive_tenant_slug(request),
        body=body,
        params=httpx.QueryParams(request.url.query),
    )
    return relay_response(upstream)


@router.post("/chat/stream")
async def proxy_chat_stream(
    request: Request,
    _invoke: _InvokeDep,
    client: _ClientDep,
) -> Response:
    """Stream one supervisor chat turn (SSE) -> ai-agent /chat/stream.

    The body is relayed chunk-by-chunk (never buffered) so the shell renders
    tokens live; the caller's JWT travels upstream unchanged so ai-agent binds
    every delegated read to the caller, not to service credentials.
    """
    authorization = request.headers.get("authorization")
    body = await request.body()
    upstream = await forward_to_ai_agent(
        client,
        method="POST",
        upstream_path="/api/v1/ai/agents/chat/stream",
        authorization=authorization,
        tenant_slug=derive_tenant_slug(request),
        body=body,
        stream=True,
    )
    return relay_stream_response(upstream)


@router.post("/{agent_name}/invoke")
async def proxy_invoke_agent(
    request: Request,
    agent_name: str,
    _invoke: _InvokeDep,
    client: _ClientDep,
) -> Response:
    """Start one agent run -> ai-agent /api/v1/ai/agents/{}/invoke."""
    return await _proxy(request, client, f"/api/v1/ai/agents/{agent_name}/invoke")


@router.get("/{agent_name}/interrupts")
async def proxy_list_interrupts(
    request: Request,
    agent_name: str,
    _invoke: _InvokeDep,
    client: _ClientDep,
) -> Response:
    """Pending review queue -> ai-agent /api/v1/ai/agents/{}/interrupts.

    The queue exposes tool payloads (draft suggestions), so the edge requires
    erp.ai.invoke; approve/deny additionally demand erp.finance.write.
    """
    return await _proxy(request, client, f"/api/v1/ai/agents/{agent_name}/interrupts")


@router.post("/{agent_name}/interrupts/{interrupt_id}/approve")
async def proxy_approve_interrupt(
    request: Request,
    agent_name: str,
    interrupt_id: uuid.UUID,
    _decision: _DecisionDep,
    client: _ClientDep,
) -> Response:
    """Approve a pending agent interrupt and resume the run."""
    return await _proxy(
        request,
        client,
        f"/api/v1/ai/agents/{agent_name}/interrupts/{interrupt_id}/approve",
    )


@router.post("/{agent_name}/interrupts/{interrupt_id}/deny")
async def proxy_deny_interrupt(
    request: Request,
    agent_name: str,
    interrupt_id: uuid.UUID,
    _decision: _DecisionDep,
    client: _ClientDep,
) -> Response:
    """Deny a pending agent interrupt and resume the run (no-op apply)."""
    return await _proxy(
        request,
        client,
        f"/api/v1/ai/agents/{agent_name}/interrupts/{interrupt_id}/deny",
    )


# ------------------------------------------------------------------
# Conversation persistence (SKY-60 durability fix)
# ------------------------------------------------------------------


@router.get("/conversations")
async def proxy_list_conversations(
    request: Request,
    _invoke: _InvokeDep,
    client: _ClientDep,
) -> Response:
    """List conversations -> ai-agent /ai/agents/conversations."""
    return await _proxy(request, client, "/api/v1/ai/agents/conversations")


@router.post("/conversations")
async def proxy_create_conversation(
    request: Request,
    _invoke: _InvokeDep,
    client: _ClientDep,
) -> Response:
    """Create conversation -> ai-agent /ai/agents/conversations."""
    return await _proxy(request, client, "/api/v1/ai/agents/conversations")


@router.get("/conversations/{conversation_id}")
async def proxy_get_conversation(
    request: Request,
    conversation_id: uuid.UUID,
    _invoke: _InvokeDep,
    client: _ClientDep,
) -> Response:
    """Get conversation -> ai-agent /ai/agents/conversations/{id}."""
    return await _proxy(
        request,
        client,
        f"/api/v1/ai/agents/conversations/{conversation_id}",
    )


@router.post("/conversations/{conversation_id}")
async def proxy_append_message(
    request: Request,
    conversation_id: uuid.UUID,
    _invoke: _InvokeDep,
    client: _ClientDep,
) -> Response:
    """Append message -> ai-agent /ai/agents/conversations/{id}."""
    return await _proxy(
        request,
        client,
        f"/api/v1/ai/agents/conversations/{conversation_id}",
    )


@router.patch("/conversations/{conversation_id}")
async def proxy_update_conversation(
    request: Request,
    conversation_id: uuid.UUID,
    _invoke: _InvokeDep,
    client: _ClientDep,
) -> Response:
    """Update conversation -> ai-agent /ai/agents/conversations/{id}."""
    return await _proxy(
        request,
        client,
        f"/api/v1/ai/agents/conversations/{conversation_id}",
    )


@router.delete("/conversations/{conversation_id}")
async def proxy_delete_conversation(
    request: Request,
    conversation_id: uuid.UUID,
    _invoke: _InvokeDep,
    client: _ClientDep,
) -> Response:
    """Delete conversation -> ai-agent /ai/agents/conversations/{id}."""
    return await _proxy(
        request,
        client,
        f"/api/v1/ai/agents/conversations/{conversation_id}",
    )
