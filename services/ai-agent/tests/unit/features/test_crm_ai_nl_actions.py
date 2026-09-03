"""Unit tests for the deterministic CRM NL action handlers (SKY-61 C9).

Each handler is a pure async function over a fake gateway - tests construct
fixed data and assert exact answer strings and data payloads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ai_agent.features.crm.gateway import ActivityRef, LeadRef, OpportunityRef
from ai_agent.features.crm.nl_actions import (
    at_risk,
    count_deals,
    no_activity,
    value_by_stage,
)

NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
OWNER_ID = uuid.uuid4()


def _opp(
    *,
    stage: str = "negotiation",
    days_ago: int = 20,
    display_name: str | None = "Deal A",
    amount: Decimal | None = None,
    currency: str | None = None,
) -> OpportunityRef:
    return OpportunityRef(
        id=uuid.uuid4(),
        stage=stage,
        probability=60,
        has_amount=amount is not None,
        created_at=NOW - timedelta(days=days_ago),
        owner_id=OWNER_ID,
        last_stage_change_at=NOW - timedelta(days=days_ago),
        expected_close_date=None,
        display_name=display_name,
        amount=amount,
        currency=currency,
    )


def _lead(*, days_ago: int = 20, display_name: str | None = "Lead A") -> LeadRef:
    return LeadRef(
        id=uuid.uuid4(),
        status="new",
        source="website",
        created_at=NOW - timedelta(days=days_ago),
        owner_id=OWNER_ID,
        has_name=True,
        has_email=True,
        display_name=display_name,
    )


def _activity(*, days_ago: int = 0) -> ActivityRef:
    return ActivityRef(
        id=uuid.uuid4(),
        kind="call",
        completed_at=NOW - timedelta(days=days_ago),
        created_at=NOW - timedelta(days=days_ago),
    )


class FakeGateway:
    def __init__(
        self,
        *,
        leads: list[LeadRef] | None = None,
        opportunities: list[OpportunityRef] | None = None,
        activities: list[ActivityRef] | None = None,
    ) -> None:
        self._leads = leads or []
        self._opps = opportunities or []
        self._activities = activities or []

    async def get_lead(self, *, lead_id: uuid.UUID) -> LeadRef:
        raise NotImplementedError

    async def get_opportunity(self, *, opportunity_id: uuid.UUID) -> OpportunityRef:
        raise NotImplementedError

    async def list_activities_for_entity(
        self, *, entity_type: str, entity_id: uuid.UUID
    ) -> list[ActivityRef]:
        return self._activities

    async def list_leads(self, *, page: int = 1) -> list[LeadRef]:
        return self._leads

    async def list_opportunities(self, *, page: int = 1) -> list[OpportunityRef]:
        return self._opps


# ---- count_deals -----------------------------------------------------------


class TestCountDeals:
    async def test_all_stages(self) -> None:
        gw = FakeGateway(opportunities=[_opp(stage="lead"), _opp(stage="negotiation")])
        result = await count_deals(gateway=gw)
        assert result.answer == "There are 2 deals in all stages."
        assert result.data["count"] == 2

    async def test_filtered_by_stage(self) -> None:
        gw = FakeGateway(opportunities=[_opp(stage="lead"), _opp(stage="negotiation")])
        result = await count_deals(gateway=gw, stage="lead")
        assert "1 deal" in result.answer
        assert result.data["count"] == 1

    async def test_no_deals(self) -> None:
        gw = FakeGateway(opportunities=[])
        result = await count_deals(gateway=gw)
        assert "0 deals" in result.answer
        assert result.data["count"] == 0

    async def test_singular(self) -> None:
        gw = FakeGateway(opportunities=[_opp()])
        result = await count_deals(gateway=gw)
        assert "1 deal" in result.answer
        assert "are" not in result.answer


# ---- value_by_stage --------------------------------------------------------


class TestValueByStage:
    async def test_groups_by_stage_and_sums_amounts(self) -> None:
        gw = FakeGateway(
            opportunities=[
                _opp(stage="lead", amount=Decimal("1000.0000"), currency="USD"),
                _opp(stage="lead", amount=Decimal("500.0000"), currency="USD"),
                _opp(stage="negotiation", amount=Decimal("2500.0000"), currency="USD"),
            ]
        )
        result = await value_by_stage(gateway=gw)
        assert "- lead: 1500.0000 USD (2 deal(s))" in result.answer
        assert "- negotiation: 2500.0000 USD (1 deal(s))" in result.answer
        assert result.data["stages"]["lead"] == 2
        assert result.data["stage_value"]["lead"] == "1500.0000"
        assert result.data["missing_value_count"] == 0
        assert result.data["currency"] == "USD"

    async def test_stages_without_amount_are_reported_honestly(self) -> None:
        gw = FakeGateway(
            opportunities=[
                _opp(stage="lead"),
                _opp(stage="lead"),
                _opp(stage="negotiation", amount=Decimal("100.0000"), currency="EUR"),
            ]
        )
        result = await value_by_stage(gateway=gw)
        assert "- lead: no recorded value (2 deal(s))" in result.answer
        assert "- negotiation: 100.0000 EUR (1 deal(s))" in result.answer
        assert "2 deal(s) have no recorded amount" in result.answer
        assert result.data["missing_value_count"] == 2

    async def test_empty_pipeline(self) -> None:
        gw = FakeGateway(opportunities=[])
        result = await value_by_stage(gateway=gw)
        assert "No deals" in result.answer


# ---- at_risk ---------------------------------------------------------------


class TestAtRisk:
    async def test_stale_deals_flagged(self) -> None:
        gw = FakeGateway(
            opportunities=[_opp(days_ago=30)],
            activities=[_activity(days_ago=30)],
        )
        result = await at_risk(gateway=gw, now=NOW)
        assert result.data["at_risk_count"] == 1

    async def test_fresh_deals_not_flagged(self) -> None:
        gw = FakeGateway(
            opportunities=[_opp(days_ago=5)],
            activities=[_activity(days_ago=3)],
        )
        result = await at_risk(gateway=gw, now=NOW)
        assert result.data["at_risk_count"] == 0
        assert "No deals" in result.answer


# ---- no_activity -----------------------------------------------------------


class TestNoActivity:
    async def test_leads_no_activity(self) -> None:
        gw = FakeGateway(
            leads=[_lead(days_ago=30)],
            activities=[],
        )
        result = await no_activity(gateway=gw, entity_type="lead", now=NOW)
        assert result.data["count"] == 1
        assert result.data["entities"][0]["entity_type"] == "lead"

    async def test_opps_no_activity(self) -> None:
        gw = FakeGateway(
            opportunities=[_opp(days_ago=30)],
            activities=[],
        )
        result = await no_activity(gateway=gw, entity_type="opportunity", now=NOW)
        assert result.data["count"] == 1

    async def test_all_entities_scan(self) -> None:
        gw = FakeGateway(
            leads=[_lead(days_ago=30)],
            opportunities=[_opp(days_ago=30)],
            activities=[],
        )
        result = await no_activity(gateway=gw, now=NOW)
        assert result.data["count"] == 2

    async def test_fresh_entities_not_flagged(self) -> None:
        gw = FakeGateway(
            leads=[_lead(days_ago=3)],
            activities=[_activity(days_ago=1)],
        )
        result = await no_activity(gateway=gw, entity_type="lead", now=NOW)
        assert result.data["count"] == 0
        assert "All" in result.answer

    async def test_custom_days_window(self) -> None:
        gw = FakeGateway(
            leads=[_lead(days_ago=10)],
            activities=[_activity(days_ago=10)],
        )
        result = await no_activity(gateway=gw, entity_type="lead", days=7, now=NOW)
        assert result.data["count"] == 1
