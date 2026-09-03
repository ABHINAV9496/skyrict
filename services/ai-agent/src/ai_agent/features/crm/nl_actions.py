"""Deterministic CRM NL action handlers (SKY-61 Part 11 - C9).

Aggregation queries that answer natural-language questions about the CRM
pipeline. These are pure functions over the CRM gateway data - no LLM, no raw
SQL. The CRM Assistant agent (C11) dispatches to these handlers after the
user's question is classified.

Actions:
- ``count_deals``: how many opportunities exist, optionally filtered by stage.
- ``count_leads``: how many leads exist, optionally filtered by status.
- ``value_by_stage``: total pipeline value grouped by stage.
- ``pipeline_summary``: full pipeline overview (leads + opportunities + stages).
- ``at_risk``: opportunities with yellow/red deal health.
- ``no_activity``: entities (leads/opportunities) with no activity in N days.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_agent.features.crm.gateway import (
        ActivityRef,
        CrmGatewayPort,
    )

# Default inactivity window for no_activity queries.
_DEFAULT_NO_ACTIVITY_DAYS = 14


@dataclass(frozen=True, slots=True)
class CrmActionResult:
    """A deterministic answer to a CRM aggregation question."""

    answer: str
    data: dict[str, object]


async def count_deals(
    *,
    gateway: CrmGatewayPort,
    stage: str | None = None,
) -> CrmActionResult:
    """Count opportunities, optionally filtered by stage."""
    opportunities = await gateway.list_opportunities()
    if stage:
        filtered = [o for o in opportunities if o.stage.lower() == stage.lower()]
        stage_label = stage
    else:
        filtered = opportunities
        stage_label = "all stages"

    count = len(filtered)
    answer = f"There {_are(count)} {count} {'deal' if count == 1 else 'deals'} in {stage_label}."
    return CrmActionResult(
        answer=answer,
        data={"count": count, "stage_filter": stage},
    )


async def count_leads(
    *,
    gateway: CrmGatewayPort,
    status: str | None = None,
) -> CrmActionResult:
    """Count leads, optionally filtered by status."""
    leads = await gateway.list_leads()
    if status:
        filtered = [lead for lead in leads if lead.status.lower() == status.lower()]
        status_label = status
    else:
        filtered = leads
        status_label = "all statuses"

    count = len(filtered)
    answer = f"There {_are(count)} {count} {'lead' if count == 1 else 'leads'} in {status_label}."
    return CrmActionResult(
        answer=answer,
        data={"count": count, "status_filter": status},
    )


async def pipeline_summary(
    *,
    gateway: CrmGatewayPort,
) -> CrmActionResult:
    """Full pipeline overview: lead count, opportunity count, and stage breakdown."""
    leads = await gateway.list_leads()
    opportunities = await gateway.list_opportunities()

    lead_count = len(leads)
    opp_count = len(opportunities)

    # Lead status breakdown
    lead_statuses: dict[str, int] = {}
    for lead in leads:
        lead_statuses[lead.status] = lead_statuses.get(lead.status, 0) + 1

    # Opportunity stage breakdown
    stage_counts: dict[str, int] = {}
    for opp in opportunities:
        stage_counts[opp.stage] = stage_counts.get(opp.stage, 0) + 1

    lines = [
        f"**Leads**: {lead_count} total",
    ]
    for status, count in sorted(lead_statuses.items()):
        lines.append(f"  - {status}: {count}")

    lines.append(f"\n**Opportunities**: {opp_count} total")
    for stage, count in sorted(stage_counts.items()):
        lines.append(f"  - {stage}: {count}")

    answer = "\n".join(lines) if lines else "No CRM data available yet."
    return CrmActionResult(
        answer=answer,
        data={
            "lead_count": lead_count,
            "opp_count": opp_count,
            "lead_statuses": lead_statuses,
            "stages": stage_counts,
        },
    )


async def value_by_stage(
    *,
    gateway: CrmGatewayPort,
) -> CrmActionResult:
    """Total pipeline value grouped by stage.

    Uses the real deal ``amount``/``currency`` values the gateway carries for
    ``erp.crm.read`` holders. Deals without a recorded value are reported in a
    running count so the total is still transparent.
    """
    opportunities = await gateway.list_opportunities()
    stage_value: dict[str, Decimal] = {}
    stage_counts: dict[str, int] = {}
    missing_value = 0
    currency: str | None = None
    for opp in opportunities:
        stage_counts[opp.stage] = stage_counts.get(opp.stage, 0) + 1
        if opp.amount is None:
            missing_value += 1
            continue
        currency = currency or opp.currency
        stage_value[opp.stage] = stage_value.get(opp.stage, Decimal("0")) + opp.amount

    currency_label = f" {currency}" if currency else ""
    lines = []
    for stage, total in sorted(stage_value.items()):
        lines.append(f"- {stage}: {total}{currency_label} ({stage_counts[stage]} deal(s))")
    # Stages present but with no recorded amount still appear so the count is honest.
    for stage, count in sorted(stage_counts.items()):
        if stage not in stage_value:
            lines.append(f"- {stage}: no recorded value ({count} deal(s))")

    answer = (
        "Pipeline value by stage:\n" + "\n".join(lines) if lines else "No deals in the pipeline."
    )
    if missing_value:
        answer += f"\nNote: {missing_value} deal(s) have no recorded amount."

    return CrmActionResult(
        answer=answer,
        data={
            "stage_value": {k: str(v) for k, v in stage_value.items()},
            "stages": stage_counts,
            "missing_value_count": missing_value,
            "currency": currency,
        },
    )


async def at_risk(
    *,
    gateway: CrmGatewayPort,
    now: datetime | None = None,
) -> CrmActionResult:
    """List opportunities with stale activity (no activity > 14 days).

    This is a lightweight subset of deal health - it flags deals without
    running the full health engine (which needs core's opportunity signals).
    """
    clock = now or datetime.now(UTC)
    opportunities = await gateway.list_opportunities()
    at_risk_deals: list[dict[str, object]] = []

    for opp in opportunities:
        activities = await gateway.list_activities_for_entity(
            entity_type="opportunity",
            entity_id=opp.id,
        )
        if not activities:
            stale_days = (clock - opp.created_at).total_seconds() / 86400.0
        else:
            latest = max(a.created_at for a in activities)
            stale_days = (clock - latest).total_seconds() / 86400.0

        if stale_days > _DEFAULT_NO_ACTIVITY_DAYS:
            at_risk_deals.append(
                {
                    "opportunity_id": str(opp.id),
                    "stage": opp.stage,
                    "days_inactive": int(stale_days),
                }
            )

    count = len(at_risk_deals)
    answer = (
        f"{count} {'deal' if count == 1 else 'deals'} "
        f"{'is' if count == 1 else 'are'} at risk (no activity for >{_DEFAULT_NO_ACTIVITY_DAYS} days)."
        if count
        else "No deals are currently at risk."
    )
    return CrmActionResult(
        answer=answer,
        data={"at_risk_count": count, "deals": at_risk_deals},
    )


async def no_activity(
    *,
    gateway: CrmGatewayPort,
    entity_type: str | None = None,
    days: int = _DEFAULT_NO_ACTIVITY_DAYS,
    now: datetime | None = None,
) -> CrmActionResult:
    """List entities (leads and/or opportunities) with no activity in N days."""
    clock = now or datetime.now(UTC)
    cutoff = clock - timedelta(days=days)
    results: list[dict[str, object]] = []

    scan_leads = entity_type in (None, "lead")
    scan_opps = entity_type in (None, "opportunity")

    if scan_leads:
        leads = await gateway.list_leads()
        for lead in leads:
            activities = await gateway.list_activities_for_entity(
                entity_type="lead",
                entity_id=lead.id,
            )
            recent = [a for a in activities if a.created_at >= cutoff]
            if not recent:
                stale_days = _staleness_days(lead.created_at, activities, clock)
                results.append(
                    {
                        "entity_type": "lead",
                        "entity_id": str(lead.id),
                        "display_name": lead.display_name,
                        "days_inactive": int(stale_days),
                    }
                )

    if scan_opps:
        opportunities = await gateway.list_opportunities()
        for opp in opportunities:
            activities = await gateway.list_activities_for_entity(
                entity_type="opportunity",
                entity_id=opp.id,
            )
            recent = [a for a in activities if a.created_at >= cutoff]
            if not recent:
                stale_days = _staleness_days(opp.created_at, activities, clock)
                results.append(
                    {
                        "entity_type": "opportunity",
                        "entity_id": str(opp.id),
                        "display_name": opp.display_name,
                        "days_inactive": int(stale_days),
                    }
                )

    count = len(results)
    entity_label = entity_type or "entities"
    answer = (
        f"{count} {entity_label} {'has' if count == 1 else 'have'} "
        f"no activity in the last {days} days."
        if count
        else f"All {entity_label} have been active in the last {days} days."
    )
    return CrmActionResult(
        answer=answer,
        data={"count": count, "entities": results},
    )


def _staleness_days(
    created_at: datetime,
    activities: list[ActivityRef],
    now: datetime,
) -> float:
    """How many days since the last activity (or creation if no activities)."""
    if not activities:
        return (now - created_at).total_seconds() / 86400.0
    latest = max(a.created_at for a in activities)
    return (now - latest).total_seconds() / 86400.0


def _are(count: int) -> str:
    return "is" if count == 1 else "are"
