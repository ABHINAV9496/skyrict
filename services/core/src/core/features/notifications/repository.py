"""Notification repository (SKY-93) - Postgres backend.

One repository per concern, shared ``AsyncSession``:

- :class:`NotificationEventRepository` - event inserts (idempotent),
  list recipients for a tenant (worker), list batch candidates.
- :class:`NotificationRepository` - inbox queries, mark read/snooze, digest
  creation, batch suppression.
- :class:`NotificationPrefRepository` - per-user, per-category prefs
  (create on first read, enforce mandatory override).

RLS scoping: ``TenantContext`` is set by the middleware (request-path) or
the batching worker (per-tenant), so every query in a given session is
scoped to one tenant. ``erp_notifications`` is further filtered to the
``recipient_user_id`` = caller; the batching worker runs under the owner
role which bypasses RLS but the extra filter is still applied.

Idempotent insert: ``ON CONFLICT DO NOTHING`` is used throughout. The
conflict target is always the unique constraint for the table, so a retry
never creates a duplicate row and the affected-row count is the canonical
"was this new?" signal.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from core.core.logging import get_logger
from core.features.notifications.categories import (
    CATEGORIES,
    NotificationCategorySpec,
)
from core.features.notifications.models.event import ErpNotificationEventModel
from core.features.notifications.models.notification import ErpNotificationModel
from core.features.notifications.models.preference import ErpNotificationPrefModel

logger = get_logger("core.notifications.repo")


def _rowcount(result: Any) -> int:
    """Affected-row count of a DML result (runtime type is CursorResult)."""
    return result.rowcount if isinstance(result, CursorResult) else 0


@dataclass(frozen=True)
class PrefView:
    """Effective preference for one category (stored row OR registry default).

    The producer and the preferences API always work with the effective
    view; a category without a stored row resolves to the registry defaults.
    """

    category: str
    in_app_on: bool
    email_on: bool
    webhook_on: bool

    @classmethod
    def from_spec(cls, spec: NotificationCategorySpec) -> PrefView:
        return cls(
            category=spec.key,
            in_app_on=spec.default_in_app,
            email_on=spec.default_email,
            webhook_on=spec.default_webhook,
        )


# ---------------------------------------------------------------------------
# Event repository
# ---------------------------------------------------------------------------


class NotificationEventRepository:
    """Manages ``erp_notification_events`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_event(
        self,
        *,
        tenant_id: uuid.UUID,
        dedupe_key: str,
        event_type: str,
        category: str,
        module: str,
        severity: str,
        title: str,
        body: str,
        recipient_kind: str,
        recipient_value: list[Any],
        relevance_key: str | None,
        payload: dict[str, Any] | None,
        is_dismissible: bool,
        occurred_at: datetime,
        created_by: uuid.UUID | None,
    ) -> uuid.UUID | None:
        """Insert a producer event (idempotent by dedupe key).

        Returns the event id when inserted, ``None`` when the event was
        already present (deduped).
        """
        stmt = (
            pg_insert(ErpNotificationEventModel)
            .values(
                tenant_id=tenant_id,
                dedupe_key=dedupe_key,
                event_type=event_type,
                category=category,
                module=module,
                severity=severity,
                title=title,
                body=body,
                recipient_kind=recipient_kind,
                recipient_value=recipient_value,
                relevance_key=relevance_key,
                payload=payload,
                is_dismissible=is_dismissible,
                occurred_at=occurred_at,
                created_by=created_by,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "dedupe_key"])
            .returning(ErpNotificationEventModel.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_tenant_ids(self) -> list[uuid.UUID]:
        """Distinct tenant ids with non-suppressed unread low/medium notifications.

        Used by the batching worker to limit its scope to tenants that have
        candidate rows.
        """
        stmt = (
            select(ErpNotificationModel.tenant_id)
            .where(
                ErpNotificationModel.digest_suppressed.is_(False),
                ErpNotificationModel.read_at.is_(None),
                ErpNotificationModel.severity.in_(["low", "medium"]),
                ErpNotificationModel.is_digest.is_(False),
                ErpNotificationModel.is_pinned.is_(False),
            )
            .distinct()
        )
        result = await self._session.execute(stmt)
        return [row[0] for row in result.all()]


# ---------------------------------------------------------------------------
# Notification repository
# ---------------------------------------------------------------------------


class NotificationRepository:
    """Manages ``erp_notifications`` rows: inbox queries, actions, batching."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_notification(
        self,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID | None,
        recipient_user_id: uuid.UUID,
        dedupe_key: str,
        category: str,
        module: str,
        severity: str,
        event_type: str,
        title: str,
        body: str,
        priority_score: int,
        pinned: bool,
        is_dismissible: bool,
        channels: dict[str, bool],
        payload: dict[str, Any] | None,
        occurred_at: datetime,
        created_by: uuid.UUID | None,
    ) -> uuid.UUID | None:
        """Insert one recipient notification (idempotent by recipient + key).

        Returns the notification id when inserted, ``None`` when the row was
        already present (deduped - a re-emission).
        """
        stmt = (
            pg_insert(ErpNotificationModel)
            .values(
                tenant_id=tenant_id,
                event_id=event_id,
                recipient_user_id=recipient_user_id,
                dedupe_key=dedupe_key,
                category=category,
                module=module,
                severity=severity,
                event_type=event_type,
                title=title,
                body=body,
                priority_score=priority_score,
                is_pinned=pinned,
                is_dismissible=is_dismissible,
                channels=channels,
                payload=payload,
                occurred_at=occurred_at,
                created_by=created_by,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "recipient_user_id", "dedupe_key"])
            .returning(ErpNotificationModel.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def batch_insert_notifications(
        self,
        rows: list[dict[str, Any]],
    ) -> Sequence[ErpNotificationModel]:
        """Insert many notification rows in one statement (idempotent).

        Returns the ORM rows actually inserted (conflict suppresses
        duplicates), so callers can dispatch channels exactly once per new
        row.
        """
        if not rows:
            return []
        stmt = (
            pg_insert(ErpNotificationModel)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["tenant_id", "recipient_user_id", "dedupe_key"])
            .returning(ErpNotificationModel)
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    # ---- inbox queries ----

    def _inbox_base(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        now: datetime,
    ) -> Any:
        """Shared WHERE clause for inbox queries (snooze + suppress filters)."""
        return and_(
            ErpNotificationModel.tenant_id == tenant_id,
            ErpNotificationModel.recipient_user_id == user_id,
            ErpNotificationModel.digest_suppressed.is_(False),
            or_(
                ErpNotificationModel.snoozed_until.is_(None),
                ErpNotificationModel.snoozed_until <= now,
            ),
        )

    async def inbox(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        category: str | None = None,
        unread_only: bool,
        now: datetime,
    ) -> tuple[Sequence[ErpNotificationModel], int]:
        """Return the paginated inbox and total matching count."""
        base = self._inbox_base(tenant_id, user_id, now=now)
        if category:
            base = and_(base, ErpNotificationModel.category == category)
        if unread_only:
            base = and_(base, ErpNotificationModel.read_at.is_(None))

        count_stmt = select(func.count()).select_from(ErpNotificationModel).where(base)
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        items_stmt = (
            select(ErpNotificationModel)
            .where(base)
            .order_by(
                ErpNotificationModel.is_pinned.desc(),
                ErpNotificationModel.priority_score.desc(),
                ErpNotificationModel.occurred_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        items_result = await self._session.execute(items_stmt)
        items = items_result.scalars().all()
        return items, total

    async def counts(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        now: datetime,
    ) -> tuple[int, int]:
        """Return (unread_count, pinned_unread_count)."""
        base = self._inbox_base(tenant_id, user_id, now=now)
        unread_stmt = (
            select(func.count())
            .select_from(ErpNotificationModel)
            .where(and_(base, ErpNotificationModel.read_at.is_(None)))
        )
        pinned_stmt = (
            select(func.count())
            .select_from(ErpNotificationModel)
            .where(
                and_(
                    base,
                    ErpNotificationModel.is_pinned.is_(True),
                    ErpNotificationModel.read_at.is_(None),
                )
            )
        )
        unread = (await self._session.execute(unread_stmt)).scalar_one()
        pinned = (await self._session.execute(pinned_stmt)).scalar_one()
        return unread, pinned

    async def get_notification_for_user(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        notification_id: uuid.UUID,
    ) -> ErpNotificationModel | None:
        """Fetch one notification scoped to the recipient (RLS + filter)."""
        stmt = select(ErpNotificationModel).where(
            ErpNotificationModel.tenant_id == tenant_id,
            ErpNotificationModel.id == notification_id,
            ErpNotificationModel.recipient_user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_read(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        notification_id: uuid.UUID,
        *,
        now: datetime,
    ) -> bool:
        """Mark one notification read. Returns True when updated."""
        stmt = (
            update(ErpNotificationModel)
            .where(
                ErpNotificationModel.tenant_id == tenant_id,
                ErpNotificationModel.id == notification_id,
                ErpNotificationModel.recipient_user_id == user_id,
                ErpNotificationModel.read_at.is_(None),
            )
            .values(read_at=now)
        )
        result = await self._session.execute(stmt)
        return _rowcount(result) > 0

    async def mark_all_read(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        now: datetime,
    ) -> int:
        """Mark every unsuppressed unread notification read. Return count."""
        stmt = (
            update(ErpNotificationModel)
            .where(
                ErpNotificationModel.tenant_id == tenant_id,
                ErpNotificationModel.recipient_user_id == user_id,
                ErpNotificationModel.read_at.is_(None),
                ErpNotificationModel.digest_suppressed.is_(False),
            )
            .values(read_at=now)
        )
        result = await self._session.execute(stmt)
        return _rowcount(result)

    async def snooze(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        notification_id: uuid.UUID,
        *,
        until: datetime,
    ) -> bool:
        """Snooze a notification. Returns True when updated."""
        stmt = (
            update(ErpNotificationModel)
            .where(
                ErpNotificationModel.tenant_id == tenant_id,
                ErpNotificationModel.id == notification_id,
                ErpNotificationModel.recipient_user_id == user_id,
            )
            .values(snoozed_until=until)
        )
        result = await self._session.execute(stmt)
        return _rowcount(result) > 0

    # ---- batching helpers ----

    async def select_batch_candidates(
        self,
        tenant_id: uuid.UUID,
        *,
        window_start: datetime,
        now: datetime,
        mandatory_keys: frozenset[str],
    ) -> Sequence[ErpNotificationModel]:
        """Return low/medium notifications eligible for digest collapse.

        Candidates: non-pinned, non-suppressed, non-digest, unread, batchable
        severity, within the window, and NOT a mandatory category.
        """
        stmt = (
            select(ErpNotificationModel)
            .where(
                ErpNotificationModel.tenant_id == tenant_id,
                ErpNotificationModel.digest_suppressed.is_(False),
                ErpNotificationModel.read_at.is_(None),
                ErpNotificationModel.severity.in_(["low", "medium"]),
                ErpNotificationModel.is_digest.is_(False),
                ErpNotificationModel.is_pinned.is_(False),
                ErpNotificationModel.occurred_at >= window_start,
                ErpNotificationModel.occurred_at <= now,
                ErpNotificationModel.category.notin_(list(mandatory_keys)),
            )
            .order_by(
                ErpNotificationModel.module,
                ErpNotificationModel.category,
                ErpNotificationModel.recipient_user_id,
                ErpNotificationModel.occurred_at,
            )
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def create_digest(
        self,
        *,
        tenant_id: uuid.UUID,
        dedupe_key: str,
        recipient_user_id: uuid.UUID,
        category: str,
        module: str,
        digest_count: int,
        title: str,
        body: str,
        priority_score: int,
        channels: dict[str, bool],
        occurred_at: datetime,
        payload: dict[str, Any] | None = None,
    ) -> uuid.UUID | None:
        """Insert a digest row (idempotent). Returns id when inserted."""
        stmt = (
            pg_insert(ErpNotificationModel)
            .values(
                tenant_id=tenant_id,
                event_id=None,
                recipient_user_id=recipient_user_id,
                dedupe_key=dedupe_key,
                category=category,
                module=module,
                severity="low",  # digests are always the lowest tier
                event_type="batch.digest",
                title=title,
                body=body,
                is_digest=True,
                digest_count=digest_count,
                digest_suppressed=False,
                is_pinned=False,
                is_dismissible=True,
                priority_score=priority_score,
                channels=channels,
                payload=payload,
                occurred_at=occurred_at,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "recipient_user_id", "dedupe_key"])
            .returning(ErpNotificationModel.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def suppress_batch_members(
        self,
        tenant_id: uuid.UUID,
        notification_ids: Sequence[uuid.UUID],
    ) -> int:
        """Mark members of a batch as ``digest_suppressed`` (idempotent)."""
        if not notification_ids:
            return 0
        stmt = (
            update(ErpNotificationModel)
            .where(
                ErpNotificationModel.tenant_id == tenant_id,
                ErpNotificationModel.id.in_(notification_ids),
            )
            .values(digest_suppressed=True)
        )
        result = await self._session.execute(stmt)
        return _rowcount(result)


# ---------------------------------------------------------------------------
# Preferences repository
# ---------------------------------------------------------------------------


class NotificationPrefRepository:
    """Manages ``erp_notification_prefs`` rows (create-on-first-read, update)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_prefs_for_user(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> dict[str, PrefView]:
        """Return {category_key: effective pref} for every category.

        Categories without a stored row resolve to the registry defaults, so
        callers never special-case the absence of a preference.
        """
        stored = await self.get_pref_rows_for_user(tenant_id, user_id)
        rows = {row.category: row for row in stored}

        out: dict[str, PrefView] = {}
        for key, spec in CATEGORIES.items():
            row = rows.get(key)
            out[key] = (
                PrefView(
                    category=row.category,
                    in_app_on=row.in_app_on,
                    email_on=row.email_on,
                    webhook_on=row.webhook_on,
                )
                if row is not None
                else PrefView.from_spec(spec)
            )
        return out

    async def get_pref_rows_for_user(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[ErpNotificationPrefModel]:
        """Return stored pref rows only (for API responses)."""
        stmt = select(ErpNotificationPrefModel).where(
            ErpNotificationPrefModel.tenant_id == tenant_id,
            ErpNotificationPrefModel.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def upsert_pref(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        category: str,
        in_app_on: bool,
        email_on: bool,
        webhook_on: bool,
    ) -> ErpNotificationPrefModel:
        """Insert or update one pref row (idempotent). Returns the row."""
        # First try insert; on conflict update.
        stmt = (
            pg_insert(ErpNotificationPrefModel)
            .values(
                tenant_id=tenant_id,
                user_id=user_id,
                category=category,
                in_app_on=in_app_on,
                email_on=email_on,
                webhook_on=webhook_on,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "user_id", "category"],
                set_={
                    "in_app_on": in_app_on,
                    "email_on": email_on,
                    "webhook_on": webhook_on,
                },
            )
            .returning(ErpNotificationPrefModel)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()
