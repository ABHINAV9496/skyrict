"""Anomaly service - detection scan + review workflow (spec §4.3/§4.4).

``run_scan`` fetches the recent movement window through the gateway, runs
the deterministic rule set, dedupes against OPEN anomalies of the same
type, and persists new findings with audit events. ``review`` applies the
open -> resolved | dismissed | escalated transitions.

Admin notification (spec §4.3 "Email to admin (critical only)"): every
critical detection and every escalated review dispatches an alert email
through the injected :class:`EmailService`. Dispatch is gated by
(1) addresses being configured, (2) the injected ``notify_enabled``
predicate (per-tenant ``email_alerts_enabled``, evaluated by the router's
composition root) and (3) severity == ``critical``. Delivery failures are
logged, never raised - audit events stay the source of truth.

Rule stats feedback (spec §4.5): every NEW detection bumps the finding
counter and every dismissal bumps the false-positive counter of the
:class:`RuleStatsRecorder` (implemented by AnomalyRuleStatsRepository at
the composition root - the feature layer never imports DB modules). These
counters drive the per-rule FP-rate tuning loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import structlog

from ai_agent.core.anomaly_email_templates import CriticalAnomalyAlert
from ai_agent.core.audit_events import (
    AI_ANOMALY_DETECTED,
    AI_ANOMALY_DISMISSED,
    AI_ANOMALY_ESCALATED,
    AI_ANOMALY_RESOLVED,
)
from ai_agent.features.anomalies.rules import detect_all
from skyrict_common.exceptions import ConflictError

if TYPE_CHECKING:
    import uuid
    from collections.abc import Awaitable, Callable

    from ai_agent.core.audit_service import AuditService
    from ai_agent.core.email import EmailService
    from ai_agent.db.anomaly_repository import AnomalyRepository
    from ai_agent.features.nl_query.gateway import InventoryGatewayPort
    from ai_agent.models.ai_anomaly import AiAnomalyModel

logger = structlog.get_logger("ai_agent.anomaly_service")

# status -> allowed source statuses (spec §4.4 workflow)
_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "resolved": ("open",),
    "dismissed": ("open",),
    "escalated": ("open", "resolved"),
}


class RuleStatsRecorder(Protocol):
    """Per-rule detection-outcome counters for the sensitivity tuning loop.

    AnomalyRuleStatsRepository implements this structurally at the router's
    composition root; the feature layer depends only on this interface so
    DB details never leak into the service (import-linter contract).
    """

    async def bump_finding(self, *, tenant_id: uuid.UUID, anomaly_type: str) -> None: ...

    async def bump_false_positive(self, *, tenant_id: uuid.UUID, anomaly_type: str) -> None: ...


@dataclass(frozen=True, slots=True)
class DetectionReport:
    detected: int
    duplicates_skipped: int


class AnomalyService:
    """Detection and review orchestration."""

    def __init__(
        self,
        *,
        gateway_factory: Callable[[], Awaitable[InventoryGatewayPort]],
        anomalies: AnomalyRepository,
        audit: AuditService,
        email: EmailService | None = None,
        notify_addresses: tuple[str, ...] = (),
        notify_enabled: Callable[[uuid.UUID], Awaitable[bool]] | None = None,
        review_base_url: str = "",
        rule_stats: RuleStatsRecorder | None = None,
    ) -> None:
        self._gateway_factory = gateway_factory
        self._anomalies = anomalies
        self._audit = audit
        self._email = email
        self._notify_addresses = notify_addresses
        self._notify_enabled = notify_enabled
        self._review_base_url = review_base_url.rstrip("/")
        self._rule_stats = rule_stats

    async def run_scan(self, *, tenant_id: uuid.UUID) -> DetectionReport:
        """Detect anomalies over recent movements; dedupe open repeats."""
        gateway = await self._gateway_factory()
        movements = await gateway.list_movements()
        stock_levels = await gateway.get_stock_levels()
        findings = detect_all(movements, stock_levels=stock_levels)

        created = skipped = 0
        for finding in findings:
            # One OPEN anomaly per (type, product, warehouse) keeps feeds
            # actionable; resolved rows allow re-detection if the pattern
            # recurs on the same scope.
            if await self._anomalies.has_open(
                tenant_id=tenant_id,
                anomaly_type=finding.anomaly_type,
                product_id=finding.affected_product_id,
                warehouse_id=finding.affected_warehouse_id,
            ):
                skipped += 1
                continue
            row = await self._anomalies.create(
                tenant_id=tenant_id,
                anomaly_type=finding.anomaly_type,
                severity=finding.severity,
                title=finding.title,
                description=finding.description,
                affected_product_id=finding.affected_product_id,
                affected_warehouse_id=finding.affected_warehouse_id,
                related_movement_ids=finding.related_movement_ids,
            )
            await self._audit.log(
                action=AI_ANOMALY_DETECTED,
                tenant_id=tenant_id,
                input_payload={"anomaly_type": finding.anomaly_type},
                output_payload={"anomaly_id": str(row.id), "severity": finding.severity},
            )
            if self._rule_stats is not None:
                await self._rule_stats.bump_finding(
                    tenant_id=tenant_id, anomaly_type=finding.anomaly_type
                )
            if finding.severity == "critical":
                await self._notify_critical(tenant_id=tenant_id, row=row)
            created += 1

        logger.info("anomaly_scan.completed", created=created, duplicates_skipped=skipped)
        return DetectionReport(detected=created, duplicates_skipped=skipped)

    async def review(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        anomaly_id: uuid.UUID,
        decision: str,
        note: str | None,
    ) -> None:
        """Apply a review transition to one anomaly (human investigates)."""
        if decision not in _TRANSITIONS:
            raise ValueError(f"invalid review decision {decision!r}")
        row = await self._anomalies.get(tenant_id=tenant_id, anomaly_id=anomaly_id)
        if row.status not in _TRANSITIONS[decision]:
            raise ConflictError(f"Cannot {decision} an anomaly in status '{row.status}'")
        await self._anomalies.record_review(
            row=row, status=decision, reviewed_by=user_id, resolution_note=note
        )
        decision_events = {
            "resolved": AI_ANOMALY_RESOLVED,
            "dismissed": AI_ANOMALY_DISMISSED,
            "escalated": AI_ANOMALY_ESCALATED,
        }
        await self._audit.log(
            action=decision_events[decision],
            tenant_id=tenant_id,
            user_id=user_id,
            input_payload={"anomaly_id": str(anomaly_id)},
            output_payload={"decision": decision, "note": note},
        )
        if decision == "escalated":
            await self._notify_critical(tenant_id=tenant_id, row=row)
        if decision == "dismissed" and self._rule_stats is not None:
            await self._rule_stats.bump_false_positive(
                tenant_id=tenant_id, anomaly_type=row.anomaly_type
            )

    async def _notify_critical(self, *, tenant_id: uuid.UUID, row: AiAnomalyModel) -> None:
        """Dispatch the admin alert for ONE critical anomaly (best-effort).

        Failures are swallowed by the transport; this method never raises so
        scans and reviews complete even when mail delivery is broken.
        """
        if self._email is None or not self._notify_addresses:
            return
        if self._notify_enabled is not None and not await self._notify_enabled(tenant_id):
            return
        review_url = f"{self._review_base_url}/{row.id}" if self._review_base_url else None
        alert = CriticalAnomalyAlert(
            to=", ".join(self._notify_addresses),
            tenant_id=str(tenant_id),
            anomaly_id=str(row.id),
            anomaly_type=row.anomaly_type,
            severity=row.severity,
            title=row.title,
            description=row.description,
            status=row.status,
            created_at=row.created_at.isoformat(),
            review_url=review_url,
        )
        await self._email.send_critical_anomaly_alert(alert=alert)
