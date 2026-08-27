"""``/api/v1/ai/*`` proxy routes — permission checks BEFORE forwarding.

Permission matrix (ticket [AI-INFRA-001], spec §6.3): every AI call needs
``erp.ai.invoke`` AND the module key for the touched domain —
``erp.inventory.read`` for reads, ``erp.inventory.write`` for mutations
(scan, approve/reject, anomaly dispositions). The ticket also names an
"ai.approve" module key; no such key exists in either service's catalog
yet, so the existing write key guards review actions this phase and a
dedicated approval key lands with the PO-integration ticket (documented,
not silently dropped).

The JWT is forwarded verbatim; ai-agent re-verifies it against the
relayed tenant slug (spec §1.4: AI is a proxy, not an auth bypass).

Path ids are typed ``uuid.UUID`` so FastAPI rejects anything else with
422 before the handler runs — the forwarded URL only ever embeds the
canonical hyphenated form (no ``/``, ``?`` or traversal sequences can
reach the upstream request target).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.api.deps import get_current_user, require_permission
from core.core.permissions import (
    ERP_AI_INVOKE,
    ERP_AI_NARRATOR_REFRESH,
    ERP_CRM_READ,
    ERP_FINANCE_READ,
    ERP_INVENTORY_READ,
    ERP_INVENTORY_WRITE,
    ERP_SALES_READ,
)
from core.core.tenant_resolver import derive_tenant_slug
from core.db.rbac import RbacRepository, grants_permission
from core.db.session import get_db
from core.features.ai.proxy import forward_to_ai_agent, relay_response
from skyrict_common.exceptions import PermissionDeniedError

router = APIRouter(prefix="/ai", tags=["ai"])

# Module-level singletons so each permission closure is built once
# (same pattern as features/inventory/router.py).
_require_ai_invoke = require_permission(ERP_AI_INVOKE)
_require_inventory_read = require_permission(ERP_INVENTORY_READ)
_require_inventory_write = require_permission(ERP_INVENTORY_WRITE)

_InvokeDep = Annotated[dict[str, Any], Depends(_require_ai_invoke)]
_ReadDep = Annotated[dict[str, Any], Depends(_require_inventory_read)]
_WriteDep = Annotated[dict[str, Any], Depends(_require_inventory_write)]

# --- Cross-module narrator (SKY-63) strict matrix ---------------------------
# The digest spans all four ERP domains, so a caller must hold erp.ai.invoke
# AND every module read. Force-refresh additionally needs erp.ai.narrator.refresh.
_NARRATOR_READS = (
    ERP_AI_INVOKE,
    ERP_FINANCE_READ,
    ERP_SALES_READ,
    ERP_INVENTORY_READ,
    ERP_CRM_READ,
)


def _require_all_permissions(
    *permissions: str,
) -> Callable[[], Awaitable[dict[str, Any]]]:
    """Dependency factory requiring EVERY listed permission (AND semantics)."""

    async def _check(
        current_user: dict[str, Any] = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> dict[str, Any]:
        granted = await RbacRepository(db).resolve_user_permissions(
            user_id=current_user["user_id"],
            tenant_id=current_user["tenant_id"],
        )
        for required in permissions:
            if not grants_permission(granted, required):
                raise PermissionDeniedError(f"Missing required permission: {required}")
        return current_user

    return _check


_require_narrator_reads = _require_all_permissions(*_NARRATOR_READS)
_require_narrator_refresh = _require_all_permissions(*_NARRATOR_READS, ERP_AI_NARRATOR_REFRESH)

_NarratorDep = Annotated[dict[str, Any], Depends(_require_narrator_reads)]
_NarratorRefreshDep = Annotated[dict[str, Any], Depends(_require_narrator_refresh)]


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
        # Raw query string round-trips verbatim (order + duplicates preserved).
        params=httpx.QueryParams(request.url.query),
    )
    return relay_response(upstream)


# --- NL inventory query (feature 1) ----------------------------------------


@router.post("/inventory/query")
async def proxy_nl_query(
    request: Request,
    _invoke: _InvokeDep,
    _read: _ReadDep,
    client: _ClientDep,
) -> Response:
    """Natural-language question about stock -> ai-agent /ai/query."""
    return await _proxy(request, client, "/ai/query")


@router.get("/inventory/query/history")
async def proxy_query_history(
    request: Request,
    _invoke: _InvokeDep,
    _read: _ReadDep,
    client: _ClientDep,
) -> Response:
    """Recent queries for this tenant -> ai-agent /ai/query/history."""
    return await _proxy(request, client, "/ai/query/history")


# --- Restock suggestions (feature 2) ---------------------------------------


@router.get("/suggestions")
async def proxy_list_suggestions(
    request: Request,
    _invoke: _InvokeDep,
    _read: _ReadDep,
    client: _ClientDep,
) -> Response:
    """Pending suggestions feed -> ai-agent /ai/suggestions."""
    return await _proxy(request, client, "/ai/suggestions")


@router.post("/suggestions/scan")
async def proxy_suggestion_scan(
    request: Request,
    _invoke: _InvokeDep,
    _write: _WriteDep,
    client: _ClientDep,
) -> Response:
    """Trigger the suggestion scan -> ai-agent /ai/suggestions/scan."""
    return await _proxy(request, client, "/ai/suggestions/scan")


@router.post("/suggestions/{suggestion_id}/approve")
async def proxy_approve_suggestion(
    request: Request,
    suggestion_id: uuid.UUID,
    _invoke: _InvokeDep,
    _write: _WriteDep,
    client: _ClientDep,
) -> Response:
    """Approve one pending suggestion (spec §3.4 human-in-the-loop)."""
    return await _proxy(request, client, f"/ai/suggestions/{suggestion_id}/approve")


@router.post("/suggestions/{suggestion_id}/reject")
async def proxy_reject_suggestion(
    request: Request,
    suggestion_id: uuid.UUID,
    _invoke: _InvokeDep,
    _write: _WriteDep,
    client: _ClientDep,
) -> Response:
    """Reject one pending suggestion; note feeds the feedback loop."""
    return await _proxy(request, client, f"/ai/suggestions/{suggestion_id}/reject")


# --- Stock anomalies (feature 3) --------------------------------------------


@router.get("/anomalies")
async def proxy_list_anomalies(
    request: Request,
    _invoke: _InvokeDep,
    _read: _ReadDep,
    client: _ClientDep,
) -> Response:
    """Anomaly feed -> ai-agent /ai/anomalies."""
    return await _proxy(request, client, "/ai/anomalies")


@router.post("/anomalies/scan")
async def proxy_anomaly_scan(
    request: Request,
    _invoke: _InvokeDep,
    _write: _WriteDep,
    client: _ClientDep,
) -> Response:
    """Trigger anomaly detection -> ai-agent /ai/anomalies/scan."""
    return await _proxy(request, client, "/ai/anomalies/scan")


@router.post("/anomalies/{anomaly_id}/resolve")
async def proxy_resolve_anomaly(
    request: Request,
    anomaly_id: uuid.UUID,
    _invoke: _InvokeDep,
    _write: _WriteDep,
    client: _ClientDep,
) -> Response:
    """Mark an anomaly resolved (human investigated)."""
    return await _proxy(request, client, f"/ai/anomalies/{anomaly_id}/resolve")


@router.post("/anomalies/{anomaly_id}/dismiss")
async def proxy_dismiss_anomaly(
    request: Request,
    anomaly_id: uuid.UUID,
    _invoke: _InvokeDep,
    _write: _WriteDep,
    client: _ClientDep,
) -> Response:
    """Mark an anomaly as false positive (feeds tuning)."""
    return await _proxy(request, client, f"/ai/anomalies/{anomaly_id}/dismiss")


@router.post("/anomalies/{anomaly_id}/escalate")
async def proxy_escalate_anomaly(
    request: Request,
    anomaly_id: uuid.UUID,
    _invoke: _InvokeDep,
    _write: _WriteDep,
    client: _ClientDep,
) -> Response:
    """Escalate an anomaly to admin attention."""
    return await _proxy(request, client, f"/ai/anomalies/{anomaly_id}/escalate")


# --- Cross-module intelligence narrator (SKY-63) -----------------------------

# The narrator gate needs the request-scoped session (its own dependency),
# so these routes use the client directly rather than the shared _InvokeDep
# set — the combined narrator deps already enforce invoke + all module reads.


@router.get("/narrator/digest")
async def proxy_narrator_digest(
    request: Request,
    _narrator: _NarratorDep,
    client: _ClientDep,
) -> Response:
    """Daily executive digest -> ai-agent /ai/narrator/digest."""
    return await _proxy(request, client, "/ai/narrator/digest")


@router.post("/narrator/digest/refresh")
async def proxy_narrator_refresh(
    request: Request,
    _narrator_refresh: _NarratorRefreshDep,
    client: _ClientDep,
) -> Response:
    """Force-recompute today's digest -> ai-agent /ai/narrator/digest/refresh."""
    return await _proxy(request, client, "/ai/narrator/digest/refresh")
