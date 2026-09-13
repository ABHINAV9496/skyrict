"""/ai/l4 endpoints - the L4 what-if workforce-cost planning engine (SKY-93).

Authentication happens here (JWT re-verification); authorization happened
upstream at the core monolith's proxy (``erp.ai.invoke`` + ``erp.hr.ai.planning``
checked before forwarding).  Scenarios are frozen on create: the projection
snapshot is stored as JSONB so reads are deterministic.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.api.v1.schemas.l4 import (
    ScenarioCompareItemOut,
    ScenarioCreateIn,
    ScenarioListItemOut,
    ScenarioOut,
)
from ai_agent.core.audit_service import AuditService
from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.audit_repository import AiAuditLogRepository
from ai_agent.db.l4_scenario_repository import L4ScenarioRepository
from ai_agent.features.l4.gateway import HttpL4CoreGateway
from ai_agent.features.l4.service import L4ScenarioService

router = APIRouter(prefix="/ai/l4", tags=["ai-l4-planning"])

_MAX_COMPARE = 3


def get_l4_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> L4ScenarioService:
    """Per-request service: caller's JWT + tenant slug bound to the gateway."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    return L4ScenarioService(
        gateway=HttpL4CoreGateway(
            bearer_token=token,
            tenant_slug=TenantContext.get_tenant_slug() or "",
        ),
        repository=L4ScenarioRepository(session),
        audit=AuditService(AiAuditLogRepository(session)),
    )


@router.post("/scenarios", response_model=ScenarioOut)
async def create_scenario(
    body: ScenarioCreateIn,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[L4ScenarioService, Depends(get_l4_service)],
) -> ScenarioOut:
    """Create a named what-if scenario with a frozen projection snapshot."""
    result = await service.create(
        tenant_id=current_user["tenant_id"],
        user_id=current_user["user_id"],
        name=body.name,
        description=body.description,
        base_as_of=body.base_as_of,
        horizon=body.horizon,
        actions_raw=[a.model_dump() for a in body.actions],
    )
    return ScenarioOut(**_out_dates(result))


@router.get("/scenarios", response_model=list[ScenarioListItemOut])
async def list_scenarios_route(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[L4ScenarioService, Depends(get_l4_service)],
) -> list[ScenarioListItemOut]:
    """List named scenarios for this tenant, newest first."""
    rows = await service.list_scenarios(tenant_id=current_user["tenant_id"])
    return [ScenarioListItemOut(**_out_dates(r)) for r in rows]


@router.get("/scenarios/compare", response_model=list[ScenarioCompareItemOut])
async def compare_scenarios_route(
    ids: Annotated[list[uuid.UUID], Query(...)],
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[L4ScenarioService, Depends(get_l4_service)],
) -> list[ScenarioCompareItemOut]:
    """Compare up to 3 scenarios side-by-side (stored snapshots, no recompute)."""
    if len(ids) < 2:
        raise HTTPException(status_code=422, detail="Provide at least 2 scenario IDs to compare")
    if len(ids) > _MAX_COMPARE:
        raise HTTPException(
            status_code=422,
            detail=f"Compare supports at most {_MAX_COMPARE} scenarios",
        )
    rows = await service.compare(tenant_id=current_user["tenant_id"], scenario_ids=ids)
    return [ScenarioCompareItemOut(**_out_dates(r)) for r in rows]


@router.get("/scenarios/{scenario_id}", response_model=ScenarioOut)
async def get_scenario_route(
    scenario_id: uuid.UUID,
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[L4ScenarioService, Depends(get_l4_service)],
) -> ScenarioOut:
    """Get one named scenario by ID."""
    result = await service.get(
        tenant_id=current_user["tenant_id"],
        scenario_id=scenario_id,
    )
    return ScenarioOut(**_out_dates(result))


def _out_dates(d: dict[str, Any]) -> dict[str, Any]:
    """Ensure date fields are isoformat strings for Pydantic."""
    out = dict(d)
    for key in ("base_as_of", "created_at"):
        v = out.get(key)
        if isinstance(v, date):
            out[key] = v.isoformat()
    return out
