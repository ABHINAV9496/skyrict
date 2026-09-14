"""CRM pipeline anomaly scan service (SKY-91).

Deterministic per-tenant scan that turns the committed anomaly rules
(``features/anomalies/crm_rules.py``) into persisted ``ai_crm_anomalies``
rows plus audit events. The scan is the scheduled twin of the follow-up
scan: it enumerates every open opportunity through the CRM gateway (never
touching core's tables directly), runs the rules, de-duplicates against the
open-anomaly feed, and materializes new findings.

Isolation / dedup facts:

- Only OPEN deals are scanned: ``won`` and ``lost`` are terminal stages
  (core's ``OpportunityStage``), so no finding can be produced about a deal
  that already closed.
- Deduplication is per (opportunity, rule): a rule that already has an
  ``open`` anomaly is skipped, so re-running an hourly scan never floods the
  inbox with copies. Resolving/dismissing the previous row re-arms the rule.
- The per-scan cap bounds the materialization rate for pathological tenants
  (the same reasoning as the follow-up scan's suggestion cap).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from ai_agent.core.audit_events import AI_CRM_ANOMALY_DETECTED
from ai_agent.features.anomalies.crm_rules import detect_all

if TYPE_CHECKING:
    from ai_agent.core.audit_service import AuditService
    from ai_agent.features.crm.gateway import CrmGatewayPort
    from ai_agent.features.crm.repositories import CrmAiRepository

logger = structlog.get_logger("ai_agent.crm_anomaly_scan")

# Terminal deal stages (core's OpportunityStage) - never scanned.
_CLOSED_STAGES = frozenset({"won", "lost"})

# Materialize at most this many NEW anomalies per tenant per scan so a
# pathological tenant cannot flood the inbox in one pass. Open rows are
# de-duplicated, so the cap only bounds genuinely new findings.
_MAX_FINDINGS_PER_SCAN = 100


@dataclass(frozen=True, slots=True)
class CrmAnomalyScanReport:
    """One scan pass outcome, returned to the scheduled job for logging."""

    scanned_opportunities: int
    detected: int
    duplicates_skipped: int


class CrmAnomalyScanService:
    """Runs the deterministic rules over pipeline data and persists findings."""

    def __init__(
        self,
        *,
        gateway: CrmGatewayPort,
        repo: CrmAiRepository,
        audit: AuditService,
    ) -> None:
        self._gateway = gateway
        self._repo = repo
        self._audit = audit

    async def run_scan(self, *, tenant_id: uuid.UUID) -> CrmAnomalyScanReport:
        """Evaluate every open opportunity and persist new findings.

        De-duplicates against open anomalies per (opportunity, rule), so an
        existing open row suppresses re-detection until it is resolved or
        dismissed.
        """
        scanned = 0
        detected = 0
        skipped = 0

        opportunities = await self._gateway.list_opportunities()
        for opp in opportunities:
            if opp.stage in _CLOSED_STAGES:
                continue
            scanned += 1
            if detected >= _MAX_FINDINGS_PER_SCAN:
                break
            activities = await self._gateway.list_activities_for_entity(
                entity_type="opportunity",
                entity_id=opp.id,
            )
            findings = detect_all(opportunity=opp, activities=activities)
            for finding in findings:
                if detected >= _MAX_FINDINGS_PER_SCAN:
                    break
                open_count = await self._repo.open_crm_anomaly_count_for_opportunity_and_rule(
                    tenant_id=tenant_id,
                    opportunity_id=opp.id,
                    rule_id=finding.rule_id,
                )
                if open_count > 0:
                    skipped += 1
                    continue
                row = await self._repo.create_crm_anomaly(
                    tenant_id=tenant_id,
                    opportunity_id=finding.opportunity_id,
                    rule_id=finding.rule_id,
                    severity=finding.severity,
                    title=finding.title,
                    description=finding.description,
                    context=finding.context or {},
                )
                await self._audit.log(
                    action=AI_CRM_ANOMALY_DETECTED,
                    tenant_id=tenant_id,
                    user_id=None,
                    input_payload={"opportunity_id": str(finding.opportunity_id)},
                    output_payload={
                        "anomaly_id": str(row.id),
                        "rule_id": finding.rule_id,
                        "severity": finding.severity,
                    },
                )
                detected += 1

        logger.info(
            "crm_anomaly_scan.pass_completed",
            tenant_id=str(tenant_id),
            scanned=scanned,
            detected=detected,
            duplicates_skipped=skipped,
        )
        return CrmAnomalyScanReport(
            scanned_opportunities=scanned,
            detected=detected,
            duplicates_skipped=skipped,
        )
