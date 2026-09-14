"""Notification service (SKY-93) - API-facing operations.

Every method is recipient-scoped: the caller's user id comes from the
authenticated principal and is applied to every query, so one user can never
see or mutate another's inbox (RLS enforces the same boundary at the row
level). The mandatory-category policy lives here: high/critical rows and
mandatory categories are pinned and cannot be snoozed or suppressed.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from core.core.logging import get_logger
from core.features.notifications.categories import get_category
from core.features.notifications.models.notification import ErpNotificationModel
from core.features.notifications.models.preference import ErpNotificationPrefModel
from core.features.notifications.repository import (
    NotificationPrefRepository,
    NotificationRepository,
    PrefView,
)
from skyrict_common.exceptions import ConflictError, NotFoundError

logger = get_logger("core.notifications.service")


@dataclass(frozen=True)
class InboxPage:
    """Paginated inbox payload for the API."""

    items: Sequence[ErpNotificationModel]
    total: int
    unread_count: int
    pinned_unread_count: int


@dataclass(frozen=True)
class SnoozeDecision:
    """Result of a snooze request."""

    snoozed: bool
    mandated: bool


class NotificationService:
    """Read/update operations on the caller's own inbox."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._now = now or (lambda: datetime.now(UTC))
        self._notifications = NotificationRepository(session)
        self._prefs = NotificationPrefRepository(session)

    # ------------------------------------------------------------------
    # Inbox
    # ------------------------------------------------------------------

    async def inbox(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        category: str | None,
        unread_only: bool = False,
    ) -> InboxPage:
        now = self._now()
        items, total = await self._notifications.inbox(
            tenant_id,
            user_id,
            limit=limit,
            offset=offset,
            category=category,
            unread_only=unread_only,
            now=now,
        )
        unread, pinned_unread = await self._notifications.counts(tenant_id, user_id, now=now)
        return InboxPage(
            items=items,
            total=total,
            unread_count=unread,
            pinned_unread_count=pinned_unread,
        )

    async def counts(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> tuple[int, int]:
        """Return (unread_count, pinned_unread_count) for the caller."""
        return await self._notifications.counts(tenant_id, user_id, now=self._now())

    async def mark_read(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        notification_id: uuid.UUID,
    ) -> ErpNotificationModel:
        """Mark one notification read; the caller must own it."""
        notification = await self._notifications.get_notification_for_user(
            tenant_id, user_id, notification_id
        )
        if notification is None:
            raise NotFoundError(f"Notification {notification_id} not found")
        await self._notifications.mark_read(tenant_id, user_id, notification_id, now=self._now())
        notification.read_at = self._now()
        return notification

    async def mark_all_read(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> int:
        return await self._notifications.mark_all_read(tenant_id, user_id, now=self._now())

    async def snooze(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        notification_id: uuid.UUID,
        *,
        until: datetime,
    ) -> SnoozeDecision:
        """Snooze a notification until ``until`` (mandatory rows are refused)."""
        notification = await self._notifications.get_notification_for_user(
            tenant_id, user_id, notification_id
        )
        if notification is None:
            raise NotFoundError(f"Notification {notification_id} not found")

        category = get_category(notification.category)
        if (category is not None and category.mandatory) or notification.is_pinned:
            return SnoozeDecision(snoozed=False, mandated=True)

        if until <= self._now():
            raise ConflictError("Snooze until must be in the future")

        await self._notifications.snooze(tenant_id, user_id, notification_id, until=until)
        return SnoozeDecision(snoozed=True, mandated=False)

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    async def list_preferences(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[PrefView]:
        return list((await self._prefs.get_prefs_for_user(tenant_id, user_id)).values())

    async def update_preference(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        category: str,
        in_app_on: bool,
        email_on: bool,
        webhook_on: bool,
    ) -> ErpNotificationPrefModel:
        """Upsert one category's preference row.

        Mandatory categories keep ``in_app`` forced on regardless of the
        payload (the caller's ``in_app_on`` is ignored for them).
        """
        spec = get_category(category)
        if spec is None:
            raise NotFoundError(f"Unknown notification category: {category}")

        effective_in_app = spec.mandatory or in_app_on
        if spec.mandatory and not in_app_on:
            logger.info(
                "notifications.prefs.mandatory_in_app_forced",
                category=category,
                tenant_id=str(tenant_id),
            )

        return await self._prefs.upsert_pref(
            tenant_id=tenant_id,
            user_id=user_id,
            category=category,
            in_app_on=effective_in_app,
            email_on=email_on,
            webhook_on=webhook_on,
        )


__all__ = ["InboxPage", "NotificationService", "SnoozeDecision"]
