"""Notification center integration tests - verified against REAL Postgres.

Covers the SKY-93 acceptance contract end to end through the producer SDK
and the service layer:

- fan-out to permission holders + idempotent re-emit (exactly-once rows);
- recipient-scoped inbox (user A never sees user B's rows);
- mandatory categories force in-app despite opt-out;
- batching collapses a low/medium burst into one digest per group and is
  idempotent on re-run; high severity never collapses;
- the B34 working-capital alert endpoint emits when the ratio breaches.

Every test seeds its OWN tenant (``seed_world``), so assertions are exact -
no cross-test pollution. The dev ``skyrict`` user is a superuser in the
compose stack, so RLS is bypassed here exactly as in production where the
app connects as a non-owner role; recipient isolation is asserted through
the repository's own ``recipient_user_id`` scoping.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from core.core.permissions import ERP_FINANCE_READ, ERP_INVENTORY_READ
from core.core.tenant_context import TenantContext
from core.db.session import async_session_factory
from core.domain.entities import WorkingCapitalAlert
from core.features.finance.automation import emit_working_capital_notification
from core.features.notifications.batching import NotificationBatcher
from core.features.notifications.domain import (
    NotificationDraft,
    NotificationSeverity,
    RecipientSpec,
)
from core.features.notifications.models.event import ErpNotificationEventModel
from core.features.notifications.models.notification import ErpNotificationModel
from core.features.notifications.producer import NotificationProducer
from core.features.notifications.service import NotificationService
from core.models.core_role import CoreRoleModel
from core.models.core_user_role import CoreUserRoleModel
from core.models.tenant import TenantModel
from skyrict_common.exceptions import ConflictError, NotFoundError

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


async def seed_world(session: object) -> dict[str, str]:
    """Seed one tenant + finance/inventory roles + two grant holders.

    Returns the tenant/user ids for the test. Commits so all rows are
    visible to later sessions.
    """
    tenant = uuid.uuid4()
    user_a = uuid.uuid4()  # holds erp.finance.read
    user_b = uuid.uuid4()  # holds erp.inventory.read
    finance_role = uuid.uuid4()
    inventory_role = uuid.uuid4()

    # session is an AsyncSession; the type is widened only for the helper.
    s = session  # type: ignore[assignment]

    s.add(
        TenantModel(
            id=tenant,
            name="Notification Tenant",
            slug=f"notif-{tenant.hex[:8]}",
            plan_tier="free",
            is_active=True,
        )
    )
    await s.flush()  # type: ignore[attr-defined]
    s.add_all(
        [
            CoreRoleModel(
                tenant_id=tenant,
                id=finance_role,
                name="Finance Manager",
                permissions=["erp.finance.read"],
            ),
            CoreRoleModel(
                tenant_id=tenant,
                id=inventory_role,
                name="Inventory Viewer",
                permissions=["erp.inventory.read"],
            ),
        ]
    )
    await s.flush()  # type: ignore[attr-defined]
    s.add_all(
        [
            CoreUserRoleModel(
                tenant_id=tenant,
                id=uuid.uuid4(),
                user_id=user_a,
                role_id=finance_role,
            ),
            CoreUserRoleModel(
                tenant_id=tenant,
                id=uuid.uuid4(),
                user_id=user_b,
                role_id=inventory_role,
            ),
        ]
    )
    await s.commit()  # type: ignore[attr-defined]
    return {
        "tenant": str(tenant),
        "user_a": str(user_a),
        "user_b": str(user_b),
    }


def _finance_draft(*, dedupe_key: str, severity: NotificationSeverity) -> NotificationDraft:
    return NotificationDraft(
        dedupe_key=dedupe_key,
        event_type="finance.working_capital_alert",
        category="finance",
        module="finance",
        severity=severity,
        title="Working capital below threshold",
        body="Working capital ratio dropped below the configured threshold.",
        recipients=RecipientSpec.from_permissions(ERP_FINANCE_READ),
        relevance_key=ERP_FINANCE_READ,
    )


def _inventory_low(dedupe_key: str) -> NotificationDraft:
    return NotificationDraft(
        dedupe_key=dedupe_key,
        event_type="inventory.low_stock",
        category="inventory",
        module="inventory",
        severity=NotificationSeverity.LOW,
        title=f"SKU low: {dedupe_key}",
        body="Stock level fell below the reorder point.",
        recipients=RecipientSpec.from_permissions(ERP_INVENTORY_READ),
        relevance_key=ERP_INVENTORY_READ,
    )


class TestProducerFanOut:
    @pytest.mark.asyncio
    async def test_emit_fans_out_and_reemit_is_noop(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            world = await seed_world(session)
            TenantContext.set(world["tenant"])
            producer = NotificationProducer(session, now=lambda: NOW)
            first = await producer.emit(
                _finance_draft(dedupe_key="wc.2026-01-01", severity=NotificationSeverity.HIGH)
            )
            await session.commit()
            assert first.deduped is False
            assert first.recipients == 1
            assert first.event_id is not None

            # Re-emit the identical event: nothing new may be inserted.
            second = await producer.emit(
                _finance_draft(dedupe_key="wc.2026-01-01", severity=NotificationSeverity.HIGH)
            )
            await session.commit()
            assert second.deduped is True
            assert second.recipients == 0
            assert second.event_id is None

            event_count = await session.scalar(
                select(func.count())
                .select_from(ErpNotificationEventModel)
                .where(
                    ErpNotificationEventModel.tenant_id == uuid.UUID(world["tenant"]),
                    ErpNotificationEventModel.dedupe_key == "wc.2026-01-01",
                )
            )
            assert event_count == 1

            row = await session.scalar(
                select(ErpNotificationModel).where(
                    ErpNotificationModel.tenant_id == uuid.UUID(world["tenant"]),
                    ErpNotificationModel.recipient_user_id == uuid.UUID(world["user_a"]),
                )
            )
            assert row is not None
            assert row.channels["in_app"] is True
            # Fresh high + permission-relevance boost = 70 + 10.
            assert row.priority_score == 80
            assert row.is_pinned is False
            TenantContext.reset()

    @pytest.mark.asyncio
    async def test_critical_pins_at_100(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            world = await seed_world(session)
            TenantContext.set(world["tenant"])
            outcome = await NotificationProducer(session, now=lambda: NOW).emit(
                _finance_draft(dedupe_key="critical.1", severity=NotificationSeverity.CRITICAL)
            )
            await session.commit()
            assert outcome.recipients == 1
            row = await session.scalar(
                select(ErpNotificationModel).where(
                    ErpNotificationModel.dedupe_key == "critical.1",
                    ErpNotificationModel.recipient_user_id == uuid.UUID(world["user_a"]),
                )
            )
            assert row is not None
            assert row.is_pinned is True
            assert row.priority_score == 100
            TenantContext.reset()

    @pytest.mark.asyncio
    async def test_recipient_isolation_across_users(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            world = await seed_world(session)
            TenantContext.set(world["tenant"])
            await NotificationProducer(session, now=lambda: NOW).emit(
                _finance_draft(dedupe_key="iso.1", severity=NotificationSeverity.MEDIUM)
            )
            await session.commit()

            tenant = uuid.UUID(world["tenant"])
            service = NotificationService(session, now=lambda: NOW)
            user_a_page = await service.inbox(
                tenant, uuid.UUID(world["user_a"]), limit=50, offset=0, category=None
            )
            user_b_page = await service.inbox(
                tenant, uuid.UUID(world["user_b"]), limit=50, offset=0, category=None
            )
            assert user_a_page.total == 1
            assert user_b_page.total == 0
            TenantContext.reset()

    @pytest.mark.asyncio
    async def test_explicit_user_recipients(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            world = await seed_world(session)
            TenantContext.set(world["tenant"])
            draft = NotificationDraft(
                dedupe_key="direct.1",
                event_type="payroll.reminder",
                category="payroll",
                module="payroll",
                severity=NotificationSeverity.MEDIUM,
                title="Payroll cutoff tomorrow",
                body="The payroll cutoff is tomorrow at 17:00.",
                recipients=RecipientSpec.from_users(world["user_b"]),
            )
            outcome = await NotificationProducer(session, now=lambda: NOW).emit(draft)
            await session.commit()
            assert outcome.recipients == 1
            # user_b receives it even without the payroll permission.
            page = await NotificationService(session, now=lambda: NOW).inbox(
                uuid.UUID(world["tenant"]),
                uuid.UUID(world["user_b"]),
                limit=50,
                offset=0,
                category=None,
            )
            assert any(item.category == "payroll" for item in page.items)
            TenantContext.reset()

    @pytest.mark.asyncio
    async def test_unknown_category_fails_fast(self, migrated_schema: None) -> None:
        from core.features.notifications.domain import NotificationConfigurationError

        async with async_session_factory() as session:
            world = await seed_world(session)
            TenantContext.set(world["tenant"])
            with pytest.raises(NotificationConfigurationError):
                draft = NotificationDraft(
                    dedupe_key="bad.1",
                    event_type="x",
                    category="unknown-category",
                    module="x",
                    severity=NotificationSeverity.LOW,
                    title="t",
                    body="b",
                    recipients=RecipientSpec.from_users(world["user_a"]),
                )
                await NotificationProducer(session).emit(draft)
            TenantContext.reset()


class TestServiceActions:
    @pytest.mark.asyncio
    async def test_mark_read_and_counts(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            world = await seed_world(session)
            TenantContext.set(world["tenant"])
            await NotificationProducer(session, now=lambda: NOW).emit(
                _finance_draft(dedupe_key="read.1", severity=NotificationSeverity.MEDIUM)
            )
            await session.commit()

            tenant = uuid.UUID(world["tenant"])
            user = uuid.UUID(world["user_a"])
            svc = NotificationService(session, now=lambda: NOW)

            unread, pinned = await svc.counts(tenant, user)
            assert unread == 1
            assert pinned == 0

            page = await svc.inbox(tenant, user, limit=50, offset=0, category=None)
            assert page.total == 1
            item = page.items[0]

            marked = await svc.mark_read(tenant, user, item.id)
            await session.commit()
            # read_at was set in Python; refresh it inside the awaited context
            # so the post-commit read cannot trigger a lazy reload
            # (MissingGreenlet in the async engine).
            await session.refresh(marked, attribute_names=["read_at"])
            assert marked.read_at is not None

            unread, pinned = await svc.counts(tenant, user)
            assert unread == 0
            TenantContext.reset()

    @pytest.mark.asyncio
    async def test_mark_read_unknown_notification_raises(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            world = await seed_world(session)
            svc = NotificationService(session, now=lambda: NOW)
            with pytest.raises(NotFoundError):
                await svc.mark_read(
                    uuid.UUID(world["tenant"]), uuid.UUID(world["user_a"]), uuid.uuid4()
                )
            TenantContext.reset()

    @pytest.mark.asyncio
    async def test_snooze_hides_from_inbox_until_time(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            world = await seed_world(session)
            TenantContext.set(world["tenant"])
            await NotificationProducer(session, now=lambda: NOW).emit(
                _finance_draft(dedupe_key="snooze.1", severity=NotificationSeverity.MEDIUM)
            )
            await session.commit()

            tenant = uuid.UUID(world["tenant"])
            user = uuid.UUID(world["user_a"])
            svc = NotificationService(session, now=lambda: NOW)
            page = await svc.inbox(tenant, user, limit=50, offset=0, category=None)
            item = page.items[0]

            decision = await svc.snooze(tenant, user, item.id, until=NOW + timedelta(hours=2))
            await session.commit()
            assert decision.snoozed is True
            assert decision.mandated is False

            # Hidden while snoozed...
            page = await svc.inbox(tenant, user, limit=50, offset=0, category=None)
            assert page.total == 0

            # ...and back once the snooze expires.
            later = NotificationService(session, now=lambda: NOW + timedelta(hours=3))
            page = await later.inbox(tenant, user, limit=50, offset=0, category=None)
            assert page.total == 1
            TenantContext.reset()

    @pytest.mark.asyncio
    async def test_snooze_in_past_is_conflict(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            world = await seed_world(session)
            TenantContext.set(world["tenant"])
            await NotificationProducer(session, now=lambda: NOW).emit(
                _finance_draft(dedupe_key="snooze.past", severity=NotificationSeverity.MEDIUM)
            )
            await session.commit()
            tenant = uuid.UUID(world["tenant"])
            user = uuid.UUID(world["user_a"])
            svc = NotificationService(session, now=lambda: NOW)
            page = await svc.inbox(tenant, user, limit=50, offset=0, category=None)
            with pytest.raises(ConflictError):
                await svc.snooze(tenant, user, page.items[0].id, until=NOW - timedelta(hours=1))
            TenantContext.reset()

    @pytest.mark.asyncio
    async def test_mandatory_opt_out_is_overridden_on_emit(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            world = await seed_world(session)
            TenantContext.set(world["tenant"])
            tenant = uuid.UUID(world["tenant"])
            user = uuid.UUID(world["user_a"])

            svc = NotificationService(session, now=lambda: NOW)
            pref = await svc.update_preference(
                tenant,
                user,
                category="compliance",
                in_app_on=False,
                email_on=False,
                webhook_on=False,
            )
            await session.commit()
            # in_app_on was forced back on in Python; refresh it inside the
            # awaited context so the post-commit read cannot trigger a lazy
            # reload (MissingGreenlet in the async engine).
            await session.refresh(pref, attribute_names=["in_app_on"])
            assert pref.in_app_on is True  # mandatory forces it back on

            draft = NotificationDraft(
                dedupe_key="compliance.1",
                event_type="compliance.notice",
                category="compliance",
                module="compliance",
                severity=NotificationSeverity.HIGH,
                title="Regulatory notice",
                body="A regulatory filing is due this week.",
                recipients=RecipientSpec.from_users(world["user_a"]),
            )
            outcome = await NotificationProducer(session, now=lambda: NOW).emit(draft)
            await session.commit()
            assert outcome.recipients == 1

            row = await session.scalar(
                select(ErpNotificationModel).where(
                    ErpNotificationModel.dedupe_key == "compliance.1",
                    ErpNotificationModel.recipient_user_id == user,
                )
            )
            assert row is not None
            assert row.channels["in_app"] is True
            # Snooze is refused for mandatory rows even though it is unpinned.
            decision = await svc.snooze(tenant, user, row.id, until=NOW + timedelta(hours=1))
            assert decision.snoozed is False
            assert decision.mandated is True
            TenantContext.reset()


class TestBatching:
    @pytest.mark.asyncio
    async def test_burst_collapses_to_one_digest_idempotently(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            world = await seed_world(session)
            TenantContext.set(world["tenant"])
            for key in ("burst.1", "burst.2", "burst.3"):
                await NotificationProducer(session, now=lambda: NOW).emit(_inventory_low(key))
            await session.commit()

            tenant = uuid.UUID(world["tenant"])
            user_b = uuid.UUID(world["user_b"])
            window_start = NOW - timedelta(hours=1)

            batcher = NotificationBatcher(session)
            outcome = await batcher.batch_tenant(
                tenant_id=tenant,
                window_start=window_start,
                window_end=NOW,
            )
            await session.commit()
            assert outcome == {"digests": 1, "suppressed": 3}

            # The single digest carries the member stats.
            digest = await session.scalar(
                select(ErpNotificationModel).where(
                    ErpNotificationModel.tenant_id == tenant,
                    ErpNotificationModel.recipient_user_id == user_b,
                    ErpNotificationModel.is_digest.is_(True),
                )
            )
            assert digest is not None
            assert digest.digest_count == 3
            assert digest.payload is not None
            assert digest.payload["member_count"] == 3
            assert digest.payload["severity_counts"] == {"low": 3}
            # Top member score (low fresh + relevance = 20) minus dampener.
            assert digest.priority_score == 15

            # Suppressed members are hidden from the inbox.
            service = NotificationService(session, now=lambda: NOW)
            page = await service.inbox(tenant, user_b, limit=50, offset=0, category=None)
            assert page.total == 1
            assert page.items[0].is_digest is True

            # Re-running the batch is a no-op (digest already exists).
            rerun = await batcher.batch_tenant(
                tenant_id=tenant,
                window_start=window_start,
                window_end=NOW,
            )
            await session.commit()
            assert rerun == {"digests": 0, "suppressed": 0}
            TenantContext.reset()

    @pytest.mark.asyncio
    async def test_high_severity_never_collapses(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            world = await seed_world(session)
            TenantContext.set(world["tenant"])
            await NotificationProducer(session, now=lambda: NOW).emit(
                NotificationDraft(
                    dedupe_key="high.inventory.1",
                    event_type="inventory.critical_stock",
                    category="inventory",
                    module="inventory",
                    severity=NotificationSeverity.HIGH,
                    title="Stock critical",
                    body="A stock level is critically low.",
                    recipients=RecipientSpec.from_permissions(ERP_INVENTORY_READ),
                )
            )
            await session.commit()

            tenant = uuid.UUID(world["tenant"])
            batcher = NotificationBatcher(session)
            outcome = await batcher.batch_tenant(
                tenant_id=tenant,
                window_start=NOW - timedelta(hours=1),
                window_end=NOW,
            )
            await session.commit()
            assert outcome == {"digests": 0, "suppressed": 0}

            service = NotificationService(session, now=lambda: NOW)
            page = await service.inbox(
                tenant, uuid.UUID(world["user_b"]), limit=50, offset=0, category=None
            )
            assert page.total == 1
            assert page.items[0].is_digest is False
            TenantContext.reset()


class TestB34Hook:
    @pytest.mark.asyncio
    async def test_breach_emits_for_finance_readers_once(self, migrated_schema: None) -> None:
        as_of = date(2026, 1, 1)
        alert = WorkingCapitalAlert(
            ratio=Decimal("0.85"),
            threshold=Decimal("1.00"),
            current_assets=Decimal("85000"),
            current_liabilities=Decimal("100000"),
            alert=True,
        )
        async with async_session_factory() as session:
            world = await seed_world(session)
            TenantContext.set(world["tenant"])
            await emit_working_capital_notification(
                session,
                tenant_id=uuid.UUID(world["tenant"]),
                alert=alert,
                as_of=as_of,
            )
            await session.commit()
            rows = await session.scalars(
                select(ErpNotificationModel).where(
                    ErpNotificationModel.tenant_id == uuid.UUID(world["tenant"]),
                    ErpNotificationModel.recipient_user_id == uuid.UUID(world["user_a"]),
                    ErpNotificationModel.dedupe_key == "finance.b34.working-capital:"
                    f"{world['tenant']}:{as_of.isoformat()}",
                )
            )
            user_a_rows = list(rows)
            assert len(user_a_rows) == 1
            assert user_a_rows[0].category == "finance"
            assert user_a_rows[0].severity == NotificationSeverity.HIGH.value

            # Re-reading the same day dedupes: no second row.
            await emit_working_capital_notification(
                session,
                tenant_id=uuid.UUID(world["tenant"]),
                alert=alert,
                as_of=as_of,
            )
            await session.commit()
            count = await session.scalar(
                select(func.count())
                .select_from(ErpNotificationModel)
                .where(
                    ErpNotificationModel.tenant_id == uuid.UUID(world["tenant"]),
                    ErpNotificationModel.recipient_user_id == uuid.UUID(world["user_a"]),
                    ErpNotificationModel.dedupe_key == "finance.b34.working-capital:"
                    f"{world['tenant']}:{as_of.isoformat()}",
                )
            )
            assert count == 1
            TenantContext.reset()

    @pytest.mark.asyncio
    async def test_healthy_ratio_emits_nothing(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            world = await seed_world(session)
            TenantContext.set(world["tenant"])
            await emit_working_capital_notification(
                session,
                tenant_id=uuid.UUID(world["tenant"]),
                alert=WorkingCapitalAlert(
                    ratio=Decimal("1.20"),
                    threshold=Decimal("1.00"),
                    current_assets=Decimal("120000"),
                    current_liabilities=Decimal("100000"),
                    alert=False,
                ),
                as_of=date(2026, 1, 2),
            )
            await session.commit()
            count = await session.scalar(
                select(func.count())
                .select_from(ErpNotificationModel)
                .where(
                    ErpNotificationModel.dedupe_key == "finance.b34.working-capital:"
                    f"{world['tenant']}:2026-01-02"
                )
            )
            # A healthy ratio never emits - even on repeat reads.
            assert count == 0
            TenantContext.reset()
