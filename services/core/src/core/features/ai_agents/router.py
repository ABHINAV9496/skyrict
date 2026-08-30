"""``/api/v1/ai/agents/*`` proxy routes — permission checks BEFORE forwarding.

SKY-59 agent orchestration runs on ai-agent; the monolith edge enforces the
ERP matrix (spec 6.3, same posture as features/ai/router.py):

  invoke / list queue    erp.ai.invoke
  approve / deny         erp.ai.invoke + erp.finance.write

The decision edge demands the finance-writer grant because it is a
financial-class write (recorded Q&A decision) — defense in depth on top of
the ai-agent runtime's own tool-permission checks.

The JWT is forwarded verbatim; ai-agent re-verifies it against the relayed
tenant slug (spec 1.4: AI is a proxy, not an auth bypass). Interrupt ids are
typed ``uuid.UUID`` so FastAPI rejects anything else with 422 before the
handler runs; ``agent_name`` is a single path segment (no traversal can be
embedded), and the runtime looks it up exactly in the agent registry.
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
from core.features.ai.proxy import forward_to_ai_agent, relay_response

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
