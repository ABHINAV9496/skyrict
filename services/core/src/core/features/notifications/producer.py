"""Notification producer SDK (SKY-93) - the one entry point modules call.

Workflow of :meth:`NotificationProducer.emit`:

1. Validate the draft contract (category registered, severities valid,
   dedupe key / recipient spec sane) - fail fast on producer bugs.
2. Insert the event row idempotently (``ON CONFLICT DO NOTHING`` on the
   ``(tenant_id, dedupe_key)`` constraint). A re-emission is a pure no-op:
   recipients were already materialised on first emit.
3. Resolve recipients (explicit users / permission holders / role holders)
   through core RBAC tables.
4. For each recipient, compute the effective channel set from prefs + config
   master switches (mandatory categories force ``in_app`` on) and insert the
   delivery row idempotently with its priority score and pin flag.
5. Dispatch channel adapters for the rows actually inserted (email/webhook
   adapters are log-only this sprint).

The producer shares the request-scoped session with the calling feature, so
the event + delivery rows commit atomically with the caller's own changes.
The tenant is read from ``TenantContext`` (set by the middleware on the
request path, set explicitly by the batching worker / CLI).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.core.config import settings
from core.core.logging import get_logger
from core.core.tenant_context import TenantContext
from core.features.notifications.categories import get_category
from core.features.notifications.channels import (
    build_dispatcher,
    dispatch_channels,
    select_channels,
)
from core.features.notifications.domain import (
    RECIPIENT_KIND_PERMISSION,
    RECIPIENT_KIND_USERS,
    NotificationConfigurationError,
    NotificationDraft,
    NotificationSeverity,
    RecipientSpec,
)
from core.features.notifications.models.role_grant import (
    user_ids_for_permissions,
    user_ids_for_roles,
)
from core.features.notifications.repository import (
    NotificationEventRepository,
    NotificationPrefRepository,
    NotificationRepository,
)
from core.features.notifications.scoring import is_pinned, score_priority

logger = get_logger("core.notifications.producer")


@dataclass(frozen=True)
class EmitOutcome:
    """Result of one emission - the dedupe + fan-out summary."""

    deduped: bool
    recipients: int
    event_id: uuid.UUID | None


class NotificationProducer:
    """Producer SDK - modules call :meth:`emit` to push a notification."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._now = now or (lambda: datetime.now(UTC))
        self._events = NotificationEventRepository(session)
        self._notifications = NotificationRepository(session)
        self._prefs = NotificationPrefRepository(session)
        self._adapters = build_dispatcher(
            email_enabled=settings.NOTIF_EMAIL_ENABLED,
            webhook_enabled=settings.NOTIF_WEBHOOK_ENABLED,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def emit(self, draft: NotificationDraft) -> EmitOutcome:
        """Emit one event to its recipients (idempotent by dedupe key)."""
        self._validate(draft)
        tenant_id = uuid.UUID(TenantContext.get())
        now = self._now()
        occurred_at = draft.occurred_at or now
        spec = get_category(draft.category)
        assert spec is not None  # validated above

        # 1. Idempotent event insert - the dedupe anchor.
        event_id = await self._events.insert_event(
            tenant_id=tenant_id,
            dedupe_key=draft.dedupe_key,
            event_type=draft.event_type,
            category=draft.category,
            module=draft.module,
            severity=draft.severity.value,
            title=draft.title,
            body=draft.body,
            recipient_kind=draft.recipients.kind,
            recipient_value=list(draft.recipients.values),
            relevance_key=draft.relevance_key,
            payload=draft.payload,
            is_dismissible=draft.is_dismissible,
            occurred_at=occurred_at,
            created_by=draft.created_by,
        )
        if event_id is None:
            logger.info(
                "notifications.emit.deduped",
                dedupe_key=draft.dedupe_key,
                tenant_id=str(tenant_id),
            )
            return EmitOutcome(deduped=True, recipients=0, event_id=None)

        # 2. Resolve recipients.
        recipient_ids = await self._resolve_recipients(tenant_id, draft.recipients)

        rows: list[dict[str, Any]] = []
        for recipient_id in recipient_ids:
            pref = (await self._prefs.get_prefs_for_user(tenant_id, recipient_id)).get(
                draft.category
            )
            if pref is None:
                # Registry default (category registered above).
                in_app_on = spec.default_in_app
                email_on = spec.default_email
                webhook_on = spec.default_webhook
            else:
                in_app_on = pref.in_app_on
                email_on = pref.email_on
                webhook_on = pref.webhook_on

            channels = select_channels(
                category_mandatory=spec.mandatory,
                in_app_on=in_app_on,
                email_on=email_on,
                webhook_on=webhook_on,
                email_master_enabled=settings.NOTIF_EMAIL_ENABLED,
                webhook_master_enabled=settings.NOTIF_WEBHOOK_ENABLED,
            )
            if not any(channels.values()):
                # Non-mandatory category, user opted out of everything.
                continue

            # Role relevance applies because the recipient was resolved via
            # the module's audience (explicit user or permission/role grant).
            score = score_priority(
                severity=draft.severity,
                now=now,
                occurred_at=occurred_at,
                relevant=True,
            )
            rows.append(
                {
                    "tenant_id": tenant_id,
                    "event_id": event_id,
                    "recipient_user_id": recipient_id,
                    "dedupe_key": draft.dedupe_key,
                    "category": draft.category,
                    "module": draft.module,
                    "severity": draft.severity.value,
                    "event_type": draft.event_type,
                    "title": draft.title,
                    "body": draft.body,
                    "priority_score": score,
                    "is_pinned": is_pinned(draft.severity),
                    "is_dismissible": draft.is_dismissible,
                    "channels": channels,
                    "payload": draft.payload,
                    "occurred_at": occurred_at,
                    "created_by": draft.created_by,
                }
            )

        inserted_rows = await self._notifications.batch_insert_notifications(rows)
        inserted = len(inserted_rows)
        if inserted:
            logger.info(
                "notifications.emit.delivered",
                dedupe_key=draft.dedupe_key,
                tenant_id=str(tenant_id),
                recipients=inserted,
                category=draft.category,
                severity=draft.severity.value,
            )
            for notification in inserted_rows:
                try:
                    await dispatch_channels(
                        notification,
                        self._adapters,
                        enabled_channels=notification.channels,
                    )
                except Exception:  # pragma: no cover - delivery must not break the business tx
                    logger.exception(
                        "notifications.emit.dispatch_failed",
                        notification_id=str(notification.id),
                        tenant_id=str(tenant_id),
                    )
        return EmitOutcome(deduped=False, recipients=inserted, event_id=event_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate(self, draft: NotificationDraft) -> None:
        if get_category(draft.category) is None:
            raise NotificationConfigurationError(
                f"Unknown notification category: {draft.category!r}"
            )
        if draft.severity not in NotificationSeverity:
            raise NotificationConfigurationError(f"Invalid severity: {draft.severity!r}")
        if draft.module.strip() == "":
            raise NotificationConfigurationError("module must not be empty")

    async def _resolve_recipients(
        self,
        tenant_id: uuid.UUID,
        spec: RecipientSpec,
    ) -> list[uuid.UUID]:
        """Resolve a recipient spec to concrete user ids (deduped)."""
        if spec.kind == RECIPIENT_KIND_USERS:
            ids: list[uuid.UUID] = []
            for value in spec.values:
                try:
                    ids.append(uuid.UUID(value))
                except (ValueError, TypeError):
                    raise NotificationConfigurationError(
                        f"Invalid user id in recipients: {value!r}"
                    ) from None
            return _dedupe_uuids(ids)

        if spec.kind == RECIPIENT_KIND_PERMISSION:
            return _dedupe_uuids(
                await user_ids_for_permissions(self._session, tenant_id, list(spec.values))
            )

        # RECIPIENT_KIND_ROLE
        return _dedupe_uuids(await user_ids_for_roles(self._session, tenant_id, list(spec.values)))


def _dedupe_uuids(ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    """Dedupe while preserving order."""
    seen: set[uuid.UUID] = set()
    out: list[uuid.UUID] = []
    for item in ids:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
