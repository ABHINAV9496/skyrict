"""Unit tests for the batching engine helpers (SKY-93).

The batching contract - only low/medium candidates, one digest per
(module, category, recipient) per window, idempotent digest key, exact
suppression count - is exercised here with a stub repository so the grouping
logic runs without Postgres. The SQL/RLS half lives in the integration suite.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from core.features.notifications.batching import (
    DIGEST_DEDUPE_KEY_PREFIX,
    NotificationBatcher,
    _digest_body,
    _digest_channels,
    _digest_priority_score,
    _digest_title,
    _member_stats,
    digest_dedupe_key,
)
from core.features.notifications.models.notification import ErpNotificationModel

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
USER = uuid.uuid4()


def _member(
    *,
    module: str = "inventory",
    category: str = "inventory",
    recipient: uuid.UUID = USER,
    title: str = "Low stock",
    severity: str = "low",
    priority_score: int = 10,
    channels: dict[str, bool] | None = None,
    notification_id: uuid.UUID | None = None,
) -> ErpNotificationModel:
    return ErpNotificationModel(
        tenant_id=TENANT,
        id=notification_id or uuid.uuid4(),
        recipient_user_id=recipient,
        dedupe_key="k",
        category=category,
        module=module,
        severity=severity,
        title=title,
        body=title,
        priority_score=priority_score,
        channels=channels or {"in_app": True},
    )


class StubRepo:
    """Duck-typed NotificationRepository recording the batcher's calls."""

    def __init__(self, candidates: list[ErpNotificationModel]) -> None:
        self.candidates = candidates
        self.created_digests: list[dict[str, object]] = []
        self.suppressed_ids: list[list[uuid.UUID]] = []

    async def select_batch_candidates(
        self,
        tenant_id: uuid.UUID,
        *,
        window_start: datetime,
        now: datetime,
        mandatory_keys: frozenset[str],
    ) -> list[ErpNotificationModel]:
        assert tenant_id == TENANT
        return list(self.candidates)

    async def create_digest(self, **kwargs: object) -> uuid.UUID | None:
        self.created_digests.append(kwargs)
        return uuid.uuid4()

    async def suppress_batch_members(
        self, tenant_id: uuid.UUID, notification_ids: list[uuid.UUID]
    ) -> int:
        self.suppressed_ids.append(notification_ids)
        return len(notification_ids)


class TestDigestKey:
    def test_key_embeds_window_start(self) -> None:
        key = digest_dedupe_key(
            module="inventory",
            category="inventory",
            recipient_user_id=USER,
            window_start=NOW,
        )
        assert key.startswith(DIGEST_DEDUPE_KEY_PREFIX)
        assert key.endswith(NOW.isoformat())
        # hand-built string for the exact contract (sortable/stable)
        assert key == (f"{DIGEST_DEDUPE_KEY_PREFIX}:inventory:inventory:{USER}:{NOW.isoformat()}")

    def test_key_is_deterministic_for_same_window(self) -> None:
        a = digest_dedupe_key(module="m", category="c", recipient_user_id=USER, window_start=NOW)
        b = digest_dedupe_key(module="m", category="c", recipient_user_id=USER, window_start=NOW)
        assert a == b


class TestPureHelpers:
    def test_member_stats_counts_severity(self) -> None:
        stats = _member_stats(
            [
                _member(severity="low"),
                _member(severity="low"),
                _member(severity="medium"),
            ]
        )
        assert stats["member_count"] == 3
        assert stats["severity_counts"] == {"low": 2, "medium": 1}

    def test_digest_title_uses_category_label(self) -> None:
        assert _digest_title("inventory", "inventory", 1) == "Inventory: 1 alert"
        assert _digest_title("inventory", "inventory", 5) == "Inventory: 5 alerts"

    def test_digest_body_previews_then_truncates(self) -> None:
        members = [_member(title=f"Alert {i}") for i in range(7)]
        body = _digest_body(members)
        assert "Alert 0" in body
        assert "(+2 more)" in body

    def test_digest_priority_is_top_minus_dampener(self) -> None:
        members = [
            _member(priority_score=10),
            _member(priority_score=40),
            _member(priority_score=70),
        ]
        assert _digest_priority_score(members) == 65

    def test_digest_priority_floor_is_1(self) -> None:
        assert _digest_priority_score([_member(priority_score=0)]) == 1

    def test_digest_channels_is_union_of_members(self) -> None:
        members = [
            _member(channels={"in_app": True, "email": False, "webhook": False}),
            _member(channels={"in_app": True, "email": True, "webhook": False}),
        ]
        assert _digest_channels(members) == {
            "in_app": True,
            "email": True,
            "webhook": False,
        }


class TestBatcher:
    @pytest.mark.asyncio
    async def test_batch_tenant_groups_by_module_category_recipient(self) -> None:
        # 2 low inventory + 1 medium finance for the same user -> 2 digests,
        # all 3 suppressed.
        repo = StubRepo(
            [
                _member(module="inventory", category="inventory"),
                _member(module="inventory", category="inventory"),
                _member(module="finance", category="finance", severity="medium"),
            ]
        )
        batcher = NotificationBatcher(
            SimpleNamespace(),  # session unused by stub path
            repository=repo,  # type: ignore[arg-type]
        )
        outcome = await batcher.batch_tenant(tenant_id=TENANT, window_start=NOW, window_end=NOW)

        assert outcome == {"digests": 2, "suppressed": 3}
        assert len(repo.created_digests) == 2
        keys = {d["dedupe_key"] for d in repo.created_digests}
        assert len(keys) == 2
        assert all(str(d["recipient_user_id"]) == str(USER) for d in repo.created_digests)
        assert all(d["digest_count"] in (2, 1) for d in repo.created_digests)

    @pytest.mark.asyncio
    async def test_batch_tenant_no_candidates_is_noop(self) -> None:
        repo = StubRepo([])
        batcher = NotificationBatcher(
            SimpleNamespace(),
            repository=repo,  # type: ignore[arg-type]
        )
        outcome = await batcher.batch_tenant(tenant_id=TENANT, window_start=NOW, window_end=NOW)
        assert outcome == {"digests": 0, "suppressed": 0}
        assert repo.created_digests == []
        assert repo.suppressed_ids == []

    @pytest.mark.asyncio
    async def test_existing_digest_skips_suppression(self) -> None:
        class DigestExistsRepo(StubRepo):
            async def create_digest(self, **kwargs: object) -> uuid.UUID | None:
                return None

        repo = DigestExistsRepo([_member(module="inventory", category="inventory")])
        batcher = NotificationBatcher(
            SimpleNamespace(),
            repository=repo,  # type: ignore[arg-type]
        )
        outcome = await batcher.batch_tenant(tenant_id=TENANT, window_start=NOW, window_end=NOW)
        assert outcome == {"digests": 0, "suppressed": 0}
        assert repo.suppressed_ids == []

    @pytest.mark.asyncio
    async def test_group_below_min_count_is_left_untouched(self) -> None:
        # One group of 1 low member with min_count=2 -> neither a digest nor a
        # suppression; the lone alert stays visible in the inbox.
        repo = StubRepo([_member(module="inventory", category="inventory")])
        batcher = NotificationBatcher(
            SimpleNamespace(),
            repository=repo,  # type: ignore[arg-type]
        )
        outcome = await batcher.batch_tenant(
            tenant_id=TENANT,
            window_start=NOW,
            window_end=NOW,
            min_count=2,
        )
        assert outcome == {"digests": 0, "suppressed": 0}
        assert repo.created_digests == []
        assert repo.suppressed_ids == []
