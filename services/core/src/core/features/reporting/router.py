"""Dashboard layout CRUD router.

Endpoints:
    GET    /api/v1/dashboards/me          — read effective layout
    PUT    /api/v1/dashboards/me          — save user layout
    POST   /api/v1/dashboards/me/reset    — reset to tenant default
    POST   /api/v1/dashboards/me/events   — record widget interaction events
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, status

from core.api.deps import get_current_user, get_dashboard_service
from core.features.reporting.schemas import (
    DashboardUpdate,
    UserDashboardLayoutRead,
    WidgetEventBatchCreate,
)
from core.features.reporting.service import DashboardService

router = APIRouter(prefix="/dashboards", tags=["dashboards"])

# Keep one dependency symbol for route wiring and unit-test overrides while the
# actual database composition remains in the API dependency layer.
_get_service = get_dashboard_service


def _tenant_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["tenant_id"]
    return uuid.UUID(val) if isinstance(val, str) else val


def _user_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["user_id"]
    return uuid.UUID(val) if isinstance(val, str) else val


@router.get("/me", response_model=UserDashboardLayoutRead)
async def get_my_layout(
    current_user: dict[str, Any] = Depends(get_current_user),
    service: DashboardService = Depends(_get_service),
) -> UserDashboardLayoutRead:
    """Return the effective layout for the current user."""
    result = await service.resolve_layout(
        tenant_id=_tenant_id(current_user),
        user_id=_user_id(current_user),
    )
    return UserDashboardLayoutRead(
        layout=result["layout"],
        updated_at=result["updated_at"],
    )


@router.put("/me", response_model=UserDashboardLayoutRead, status_code=status.HTTP_200_OK)
async def save_my_layout(
    body: DashboardUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
    service: DashboardService = Depends(_get_service),
) -> UserDashboardLayoutRead:
    """Save the user's personal dashboard layout."""
    result = await service.save_user_layout(
        tenant_id=_tenant_id(current_user),
        user_id=_user_id(current_user),
        layout=[w.model_dump() for w in body.layout],
    )
    return UserDashboardLayoutRead(
        layout=result["layout"],
        updated_at=result["updated_at"],
    )


@router.post("/me/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_my_layout(
    current_user: dict[str, Any] = Depends(get_current_user),
    service: DashboardService = Depends(_get_service),
) -> None:
    """Reset the user's layout to the tenant default."""
    await service.reset_user_layout(
        tenant_id=_tenant_id(current_user),
        user_id=_user_id(current_user),
    )


@router.post("/me/events", status_code=status.HTTP_201_CREATED)
async def record_my_events(
    body: WidgetEventBatchCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
    service: DashboardService = Depends(_get_service),
) -> dict[str, Any]:
    """Record widget interaction events for the current user."""
    count = await service.record_events(
        tenant_id=_tenant_id(current_user),
        user_id=_user_id(current_user),
        events=[ev.model_dump() for ev in body.events],
    )
    return {"recorded": count}
