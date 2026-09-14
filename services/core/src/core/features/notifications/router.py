"""Notification center API (SKY-93).

Inbox / counts / read / snooze / preferences for the signed-in user's own
notifications. The endpoints are recipient-scoped: the user id comes from the
authenticated principal and every query carries it, so one user can never see
or mutate another's inbox (RLS enforces the same boundary at the row level).

No extra permission gate: any authenticated user may read their own inbox.
Notifications whose category grants a module permission are emitted to the
holders of that permission at producer time; reading your own inbox is not a
module action. Mandatory rows (e.g. compliance) will not snooze and keep
``in_app`` forced on - the policy is enforced in the service, not here.

Route ordering note: ``/read-all`` and ``/preferences`` are declared before
the ``/{notification_id}`` paths so they are never shadowed by the parameter.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Path, Query

from core.api.deps import get_current_user, get_notification_service, get_tenant_id
from core.features.notifications.categories import CATEGORIES
from core.features.notifications.schemas import (
    CountsResponse,
    InboxResponse,
    MarkAllReadResponse,
    MarkReadResponse,
    NotificationItem,
    PreferenceItem,
    PreferenceListResponse,
    PreferenceUpdate,
    SnoozeRequest,
    SnoozeResponse,
)
from core.features.notifications.service import NotificationService
from skyrict_common.exceptions import ConflictError
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _user_id(current_user: dict[str, Any]) -> uuid.UUID:
    """The authenticated principal's user id (already normalized to UUID)."""
    return uuid.UUID(str(current_user["user_id"]))


@router.get("/inbox", response_model=ResponseEnvelope[InboxResponse])
async def list_inbox(
    current_user: dict[str, Any] = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    service: NotificationService = Depends(get_notification_service),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    category: str | None = Query(default=None),
    unread_only: bool = Query(default=False),
) -> ResponseEnvelope[InboxResponse]:
    page = await service.inbox(
        tenant_id,
        _user_id(current_user),
        limit=limit,
        offset=offset,
        category=category,
        unread_only=unread_only,
    )
    return ResponseEnvelope(
        data=InboxResponse(
            items=[NotificationItem.model_validate(item) for item in page.items],
            total=page.total,
            unread_count=page.unread_count,
            pinned_unread_count=page.pinned_unread_count,
        )
    )


@router.get("/counts", response_model=ResponseEnvelope[CountsResponse])
async def get_counts(
    current_user: dict[str, Any] = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    service: NotificationService = Depends(get_notification_service),
) -> ResponseEnvelope[CountsResponse]:
    unread, pinned = await service.counts(
        tenant_id,
        _user_id(current_user),
    )
    return ResponseEnvelope(
        data=CountsResponse(
            unread_count=unread,
            pinned_unread_count=pinned,
        )
    )


@router.post("/read-all", response_model=ResponseEnvelope[MarkAllReadResponse])
async def mark_all_read(
    current_user: dict[str, Any] = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    service: NotificationService = Depends(get_notification_service),
) -> ResponseEnvelope[MarkAllReadResponse]:
    marked = await service.mark_all_read(
        tenant_id,
        _user_id(current_user),
    )
    return ResponseEnvelope(data=MarkAllReadResponse(marked=marked))


@router.get("/preferences", response_model=ResponseEnvelope[PreferenceListResponse])
async def list_preferences(
    current_user: dict[str, Any] = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    service: NotificationService = Depends(get_notification_service),
) -> ResponseEnvelope[PreferenceListResponse]:
    prefs = await service.list_preferences(
        tenant_id,
        _user_id(current_user),
    )
    items = [
        PreferenceItem(
            category=pref.category,
            label=spec.label,
            mandatory=spec.mandatory,
            in_app_on=pref.in_app_on,
            email_on=pref.email_on,
            webhook_on=pref.webhook_on,
        )
        for pref in prefs
        for spec in [CATEGORIES.get(pref.category)]
        if spec is not None
    ]
    return ResponseEnvelope(data=PreferenceListResponse(items=items))


@router.put("/preferences/{category}", response_model=ResponseEnvelope[PreferenceItem])
async def update_preferences(
    payload: PreferenceUpdate,
    category: str = Path(...),
    current_user: dict[str, Any] = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    service: NotificationService = Depends(get_notification_service),
) -> ResponseEnvelope[PreferenceItem]:
    row = await service.update_preference(
        tenant_id,
        _user_id(current_user),
        category=category,
        in_app_on=payload.in_app_on,
        email_on=payload.email_on,
        webhook_on=payload.webhook_on,
    )
    spec = CATEGORIES[category]
    return ResponseEnvelope(
        data=PreferenceItem(
            category=row.category,
            label=spec.label,
            mandatory=spec.mandatory,
            in_app_on=row.in_app_on,
            email_on=row.email_on,
            webhook_on=row.webhook_on,
        )
    )


@router.post("/{notification_id}/read", response_model=ResponseEnvelope[MarkReadResponse])
async def mark_read(
    notification_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    service: NotificationService = Depends(get_notification_service),
) -> ResponseEnvelope[MarkReadResponse]:
    updated = await service.mark_read(
        tenant_id,
        _user_id(current_user),
        notification_id,
    )
    return ResponseEnvelope(
        data=MarkReadResponse(
            id=notification_id,
            read_at=updated.read_at or datetime.now(UTC),
        )
    )


@router.post("/{notification_id}/snooze", response_model=ResponseEnvelope[SnoozeResponse])
async def snooze(
    notification_id: uuid.UUID,
    payload: SnoozeRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    service: NotificationService = Depends(get_notification_service),
) -> ResponseEnvelope[SnoozeResponse]:
    decision = await service.snooze(
        tenant_id,
        _user_id(current_user),
        notification_id,
        until=payload.until,
    )
    if decision.mandated:
        raise ConflictError("This notification cannot be snoozed")
    return ResponseEnvelope(data=SnoozeResponse(snoozed=decision.snoozed))
