"""Batching engine (SKY-93) - collapse a burst of low/medium notifications
into one digest per (module, category, recipient) per window.

The engine's contract:

- Only low/medium, non-pinned, non-mandatory-category, unread notifications
  are candidates. High/critical and mandatory (compliance) notifications are
  never collapsed.
- A digest row is inserted per group with ``is_digest=True`` and a dedupe key
  that embeds the window start, so a crash between the digest insert and the
  suppression UPDATE is idempotent on re-run (the digest 'DO NOTHING' and the
  members are already suppressed).
- Members are marked ``digest_suppressed=True`` and disappear from the inbox;
  the digest's ``digest_count`` records how many members were folded in.
- The digest itself carries the member stats ({category, count}) in
  ``payload`` so the UI can show "5 inventory alerts".

Ordering guarantee: batch happens after the worker's emit loop completed a
full pass, so every notification from this window already exists when the
candidates are selected. This makes the digest count exact.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.core.logging import get_logger
from core.features.notifications.categories import CATEGORIES
from core.features.notifications.models.notification import ErpNotificationModel
from core.features.notifications.repository import NotificationRepository

logger = get_logger("core.notifications.batching")

DIGEST_DEDUPE_KEY_PREFIX = "batch.digest"


def digest_dedupe_key(
    *,
    module: str,
    category: str,
    recipient_user_id: uuid.UUID,
    window_start: datetime,
) -> str:
    """Deterministic, idempotent key for a digest row.

    Two batches in the same window for the same module/category/recipient
    collide on purpose - re-running the engine must never create a second
    digest for the same group.
    """
    return (
        f"{DIGEST_DEDUPE_KEY_PREFIX}:{module}:{category}:{recipient_user_id}"
        f":{window_start.isoformat()}"
    )


def _member_stats(
    members: list[ErpNotificationModel],
) -> dict[str, Any]:
    """Aggregate member counts per category-level attribute for the digest payload."""
    severity_counts: dict[str, int] = {}
    for member in members:
        severity_counts[member.severity] = severity_counts.get(member.severity, 0) + 1
    return {
        "severity_counts": severity_counts,
        "member_count": len(members),
    }


def _digest_title(module: str, category: str, count: int) -> str:
    """Human title for a digest; the category label keeps it scannable."""
    spec = CATEGORIES.get(category)
    label = spec.label if spec is not None else category
    if count == 1:
        return f"{label}: {count} alert"
    return f"{label}: {count} alerts"


def _digest_body(members: list[ErpNotificationModel], limit: int = 5) -> str:
    """Summary body listing the first few member titles."""
    titles = [member.title for member in members[:limit]]
    preview = " · ".join(titles)
    extra = len(members) - len(titles)
    if extra > 0:
        preview += f" (+{extra} more)"
    return preview


class NotificationBatcher:
    """Collapses eligible notifications for one tenant in one window."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: NotificationRepository | None = None,
    ) -> None:
        self._session = session
        self._notifications = repository or NotificationRepository(session)

    async def batch_tenant(
        self,
        *,
        tenant_id: uuid.UUID,
        window_start: datetime,
        window_end: datetime,
        min_count: int = 1,
    ) -> dict[str, int]:
        """Collapse one tenant's window. Returns {digests, suppressed}.

        Groups with fewer than ``min_count`` members are left untouched -
        a lone low/medium alert does not warrant a digest, so it stays in the
        inbox as a normal notification.
        """
        now = window_end

        # 1. Select all eligible candidate rows.
        candidates = await self._notifications.select_batch_candidates(
            tenant_id,
            window_start=window_start,
            now=now,
            mandatory_keys=frozenset(key for key, spec in CATEGORIES.items() if spec.mandatory),
        )
        if not candidates:
            return {"digests": 0, "suppressed": 0}

        # 2. Group by (module, category, recipient).
        groups: dict[tuple[str, str, uuid.UUID], list[ErpNotificationModel]] = {}
        for candidate in candidates:
            groups.setdefault(
                (candidate.module, candidate.category, candidate.recipient_user_id),
                [],
            ).append(candidate)

        total_digests = 0
        total_suppressed = 0
        for (module, category, recipient_user_id), members in groups.items():
            member_count = len(members)
            if member_count < min_count:
                # Too few members for a digest - leave them untouched so the
                # inbox still shows the individual notification.
                continue
            digest_key = digest_dedupe_key(
                module=module,
                category=category,
                recipient_user_id=recipient_user_id,
                window_start=window_start,
            )
            stats = _member_stats(members)

            digest_id = await self._notifications.create_digest(
                tenant_id=tenant_id,
                dedupe_key=digest_key,
                recipient_user_id=recipient_user_id,
                category=category,
                module=module,
                digest_count=member_count,
                title=_digest_title(module, category, member_count),
                body=_digest_body(members),
                priority_score=_digest_priority_score(members),
                channels=_digest_channels(members),
                occurred_at=window_end,
                payload=stats,
            )
            if digest_id is None:
                # Digest already exists for this window - members from a
                # previous partial pass are already suppressed; skip.
                continue

            suppressed = await self._notifications.suppress_batch_members(
                tenant_id,
                [member.id for member in members],
            )
            total_digests += 1
            total_suppressed += suppressed

            logger.info(
                "notifications.batch.digest_created",
                tenant_id=str(tenant_id),
                digest_id=str(digest_id),
                module=module,
                category=category,
                recipient_user_id=str(recipient_user_id),
                member_count=member_count,
                stats=stats,
            )

        return {"digests": total_digests, "suppressed": total_suppressed}


def _digest_priority_score(members: list[ErpNotificationModel]) -> int:
    """Priority for the digest ~ highest member score minus a small dampener."""
    if not members:
        return 0
    top = max(member.priority_score or 0 for member in members)
    return max(1, top - 5)


def _digest_channels(members: list[ErpNotificationModel]) -> dict[str, bool]:
    """Union of member channels: any member on email keeps the digest on email."""
    in_app = any(member.channels.get("in_app", False) for member in members)
    email = any(member.channels.get("email", False) for member in members)
    webhook = any(member.channels.get("webhook", False) for member in members)
    return {"in_app": in_app, "email": email, "webhook": webhook}
