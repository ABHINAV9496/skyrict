"""Revenue-forecast pipeline weighting integration tests (SKY-82 A4).

``RevenueForecastRepository.pipeline_by_month`` against REAL Postgres. It must
hold in both environments it runs in: a core-only database where the ai-agent
chain has not migrated (``ai_deal_health`` is absent, so the reader must
degrade to unmodulated conversion-weight arithmetic) and a shared database
where the table exists and a live assessment feed is present. Both converge to
the same behavior here, because no ``ai_deal_health`` rows exist for this
tenant.

The conversion weight is deterministic CRM math (SKY-91): a deal with an
explicit non-zero ``probability`` is weighted ``probability/100`` (parity with
the pre-SKY-91 formula); a deal with ``probability = 0`` falls back to its
stage's historical conversion rate from the seeded ``erp_crm_timeline_events``
outcomes (``won / (won + lost)``); a stage without completed outcomes weighs
nothing. Terminal (``won``/``lost``) and null-amount / null-close
opportunities, and deals closing outside the horizon window, must be excluded
from the bucketed weighted pipeline.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from core.db.session import async_session_factory, engine
from core.domain.value_objects import (
    CrmEntityType,
    CrmTimelineEventType,
    OpportunityStage,
)
from core.features.crm.models.opportunity import ErpCrmOpportunityModel
from core.features.crm.models.timeline_event import ErpCrmTimelineEventModel
from core.features.revenue_forecast.repository import RevenueForecastRepository
from core.models.tenant import TenantModel

pytestmark = pytest.mark.integration

FROM_MONTH = date(2026, 7, 1)
TO_MONTH = date(2026, 9, 30)


@pytest.fixture(scope="module")
def pipeline_world(migrated_schema: None) -> dict[str, str]:
    """Seed one tenant plus a spread of CRM opportunities and timeline history.

    Plain (sync) fixture: all DB work runs inside one ``asyncio.run()`` and the
    engine pool is disposed before that run's loop closes, so the function-
    scoped async tests that follow get a clean pool bound to their own loops.
    """

    async def _setup() -> dict[str, str]:
        tenant_id = uuid.uuid4()
        # SKY-91 history anchors: terminal won/lost opportunities whose timeline
        # events produce historical conversion rates of proposal 0.5000
        # (2 won / 4 outcomes) and negotiation 0.2500 (1 won / 4 outcomes).
        won_proposal_ids = [uuid.uuid4(), uuid.uuid4()]
        lost_proposal_ids = [uuid.uuid4(), uuid.uuid4()]
        won_negotiation_ids = [uuid.uuid4()]
        lost_negotiation_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]

        async with async_session_factory() as session:
            session.add(
                TenantModel(
                    id=tenant_id,
                    name="Forecast Pipeline Tenant",
                    slug=f"pl-{tenant_id.hex[:8]}",
                    plan_tier="free",
                    is_active=True,
                )
            )
            await session.flush()
            session.add_all(
                [
                    ErpCrmOpportunityModel(
                        tenant_id=tenant_id,
                        name="Qualified A",
                        stage=OpportunityStage.QUALIFIED,
                        amount=Decimal("10000.0000"),
                        currency_code="USD",
                        probability=50,
                        expected_close_date=date(2026, 7, 15),
                    ),
                    ErpCrmOpportunityModel(
                        tenant_id=tenant_id,
                        name="Proposal B",
                        stage=OpportunityStage.PROPOSAL,
                        amount=Decimal("20000.0000"),
                        currency_code="USD",
                        probability=80,
                        expected_close_date=date(2026, 8, 20),
                    ),
                    ErpCrmOpportunityModel(
                        tenant_id=tenant_id,
                        name="Negotiation C",
                        stage=OpportunityStage.NEGOTIATION,
                        amount=Decimal("30000.0000"),
                        currency_code="USD",
                        probability=100,
                        expected_close_date=date(2026, 8, 28),
                    ),
                    # SKY-91: no explicit probability - weighted at the stage's
                    # historical conversion rate (proposal 0.5000 / negotiation
                    # 0.2500).
                    ErpCrmOpportunityModel(
                        tenant_id=tenant_id,
                        name="Proposal I (stage-rate)",
                        stage=OpportunityStage.PROPOSAL,
                        amount=Decimal("100000.0000"),
                        currency_code="USD",
                        probability=0,
                        expected_close_date=date(2026, 7, 25),
                    ),
                    ErpCrmOpportunityModel(
                        tenant_id=tenant_id,
                        name="Negotiation J (stage-rate)",
                        stage=OpportunityStage.NEGOTIATION,
                        amount=Decimal("200000.0000"),
                        currency_code="USD",
                        probability=0,
                        expected_close_date=date(2026, 8, 25),
                    ),
                    # Excluded: terminal stages.
                    ErpCrmOpportunityModel(
                        tenant_id=tenant_id,
                        name="Lost D",
                        stage=OpportunityStage.LOST,
                        amount=Decimal("50000.0000"),
                        currency_code="USD",
                        probability=90,
                        expected_close_date=date(2026, 8, 1),
                        lost_at=datetime(2026, 8, 2),
                    ),
                    ErpCrmOpportunityModel(
                        tenant_id=tenant_id,
                        name="Won E",
                        stage=OpportunityStage.WON,
                        amount=Decimal("40000.0000"),
                        currency_code="USD",
                        probability=100,
                        expected_close_date=date(2026, 7, 10),
                        won_at=datetime(2026, 7, 10),
                    ),
                    # Excluded: no amount, no close date, outside the window.
                    ErpCrmOpportunityModel(
                        tenant_id=tenant_id,
                        name="No Amount F",
                        stage=OpportunityStage.PROSPECTING,
                        amount=None,
                        currency_code=None,
                        probability=20,
                        expected_close_date=date(2026, 7, 1),
                    ),
                    ErpCrmOpportunityModel(
                        tenant_id=tenant_id,
                        name="No Close Date G",
                        stage=OpportunityStage.PROSPECTING,
                        amount=Decimal("90000.0000"),
                        currency_code="USD",
                        probability=25,
                        expected_close_date=None,
                    ),
                    ErpCrmOpportunityModel(
                        tenant_id=tenant_id,
                        name="Outside Horizon H",
                        stage=OpportunityStage.QUALIFIED,
                        amount=Decimal("70000.0000"),
                        currency_code="USD",
                        probability=40,
                        expected_close_date=date(2026, 10, 15),
                    ),
                ]
            )
            # The terminal history anchors (won/lost outcomes only - never
            # counted in the pipeline themselves) plus the timeline events
            # that drive the stage conversion rates.
            session.add_all(
                [
                    ErpCrmOpportunityModel(
                        id=anchor_id,
                        tenant_id=tenant_id,
                        name=f"History won {index}",
                        stage=OpportunityStage.WON,
                        amount=Decimal(f"4000{index}.0000"),
                        currency_code="USD",
                        probability=100,
                        expected_close_date=date(2026, 6, 1),
                        won_at=datetime(2026, 6, 1),
                    )
                    for index, anchor_id in enumerate(won_proposal_ids, start=1)
                ]
                + [
                    ErpCrmOpportunityModel(
                        id=anchor_id,
                        tenant_id=tenant_id,
                        name=f"History lost {index}",
                        stage=OpportunityStage.LOST,
                        amount=Decimal(f"8000{index}.0000"),
                        currency_code="USD",
                        probability=50,
                        expected_close_date=date(2026, 6, 1),
                        lost_at=datetime(2026, 6, 1),
                    )
                    for index, anchor_id in enumerate(lost_proposal_ids, start=1)
                ]
                + [
                    ErpCrmOpportunityModel(
                        id=anchor_id,
                        tenant_id=tenant_id,
                        name="History won (negotiation)",
                        stage=OpportunityStage.WON,
                        amount=Decimal("9000.0000"),
                        currency_code="USD",
                        probability=100,
                        expected_close_date=date(2026, 6, 1),
                        won_at=datetime(2026, 6, 1),
                    )
                    for anchor_id in won_negotiation_ids
                ]
                + [
                    ErpCrmOpportunityModel(
                        id=anchor_id,
                        tenant_id=tenant_id,
                        name=f"History lost (negotiation) {index}",
                        stage=OpportunityStage.LOST,
                        amount=Decimal(f"7000{index}.0000"),
                        currency_code="USD",
                        probability=50,
                        expected_close_date=date(2026, 6, 1),
                        lost_at=datetime(2026, 6, 1),
                    )
                    for index, anchor_id in enumerate(lost_negotiation_ids, start=1)
                ]
            )
            session.add_all(
                [
                    ErpCrmTimelineEventModel(
                        tenant_id=tenant_id,
                        entity_type=CrmEntityType.OPPORTUNITY,
                        entity_id=anchor_id,
                        event_type=CrmTimelineEventType.OPPORTUNITY_WON,
                        title="Opportunity won",
                        payload={"from_stage": "proposal"},
                    )
                    for anchor_id in won_proposal_ids
                ]
                + [
                    ErpCrmTimelineEventModel(
                        tenant_id=tenant_id,
                        entity_type=CrmEntityType.OPPORTUNITY,
                        entity_id=anchor_id,
                        event_type=CrmTimelineEventType.OPPORTUNITY_LOST,
                        title="Opportunity lost",
                        payload={"from_stage": "proposal"},
                    )
                    for anchor_id in lost_proposal_ids
                ]
                + [
                    ErpCrmTimelineEventModel(
                        tenant_id=tenant_id,
                        entity_type=CrmEntityType.OPPORTUNITY,
                        entity_id=anchor_id,
                        event_type=CrmTimelineEventType.OPPORTUNITY_WON,
                        title="Opportunity won",
                        payload={"from_stage": "negotiation"},
                    )
                    for anchor_id in won_negotiation_ids
                ]
                + [
                    ErpCrmTimelineEventModel(
                        tenant_id=tenant_id,
                        entity_type=CrmEntityType.OPPORTUNITY,
                        entity_id=anchor_id,
                        event_type=CrmTimelineEventType.OPPORTUNITY_LOST,
                        title="Opportunity lost",
                        payload={"from_stage": "negotiation"},
                    )
                    for anchor_id in lost_negotiation_ids
                ]
            )
            await session.commit()
            await engine.dispose()
        return {"tenant_id": str(tenant_id)}

    async def _teardown(created: str) -> None:
        async with async_session_factory() as session:
            await session.execute(
                text("DELETE FROM tenants WHERE id = :tid"), {"tid": uuid.UUID(created)}
            )
            await session.commit()
            await engine.dispose()

    created = asyncio.run(_setup())
    try:
        yield created
    finally:
        asyncio.run(_teardown(created["tenant_id"]))


async def test_pipeline_by_month_buckets_only_open_winning_window_deals(
    pipeline_world: dict[str, str],
) -> None:
    tenant_id = uuid.UUID(pipeline_world["tenant_id"])
    async with async_session_factory() as session:
        repo = RevenueForecastRepository(session)
        pipeline = await repo.pipeline_by_month(tenant_id, FROM_MONTH, TO_MONTH)
        await session.rollback()

    # A = 10000 x 50% = 5000 (Jul); I = 100000 x proposal-rate 0.5000 = 50000
    # (Jul); B + C = 20000x80% + 30000x100% = 46000 (Aug); J = 200000 x
    # negotiation-rate 0.2500 = 50000 (Aug).
    assert pipeline == {
        date(2026, 7, 1): Decimal("55000"),
        date(2026, 8, 1): Decimal("96000"),
    }
