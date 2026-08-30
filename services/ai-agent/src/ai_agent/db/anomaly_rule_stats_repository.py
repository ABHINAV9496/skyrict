"""Tenant-scoped access to ai_anomaly_rule_stats (INV-AI-002, spec §4.4).

Counters feed the sensitivity tuning loop: ``bump_finding`` / ``bump_false_positive``
record detection + dismissal outcomes per rule type; ``is_suppressed`` tells the
detection service whether a rule's rolling FP rate
``false_positives / findings_total`` has crossed the tenant threshold.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ai_agent.models.ai_anomaly_rule_stats import AiAnomalyRuleStatsModel

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


class AnomalyRuleStatsRepository:
    """Persistence for per-rule false-positive counters."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bump_finding(self, *, tenant_id: uuid.UUID, anomaly_type: str) -> None:
        """Increment the finding count for a rule (one row upsert)."""
        await self._bump(tenant_id=tenant_id, anomaly_type=anomaly_type, field="findings_total")

    async def bump_false_positive(self, *, tenant_id: uuid.UUID, anomaly_type: str) -> None:
        """Increment both counters when an anomaly is dismissed as a false positive."""
        await self._bump(tenant_id=tenant_id, anomaly_type=anomaly_type, field="false_positives")
        await self._bump(tenant_id=tenant_id, anomaly_type=anomaly_type, field="findings_total")

    async def false_positive_rate(self, *, tenant_id: uuid.UUID, anomaly_type: str) -> Decimal:
        """Rolling FP rate for a rule; 0 when the rule has no findings."""
        stmt = select(
            AiAnomalyRuleStatsModel.findings_total,
            AiAnomalyRuleStatsModel.false_positives,
        ).where(
            AiAnomalyRuleStatsModel.tenant_id == tenant_id,
            AiAnomalyRuleStatsModel.anomaly_type == anomaly_type,
        )
        result = await self.session.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return Decimal(0)
        findings = int(row.findings_total)
        if findings <= 0:
            return Decimal(0)
        return Decimal(str(row.false_positives)) / Decimal(findings)

    async def _bump(self, *, tenant_id: uuid.UUID, anomaly_type: str, field: str) -> None:
        column = getattr(AiAnomalyRuleStatsModel, field)
        stmt = (
            insert(AiAnomalyRuleStatsModel)
            .values(
                tenant_id=tenant_id,
                anomaly_type=anomaly_type,
                findings_total=0,
                false_positives=0,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "anomaly_type"],
                set_={field: column + 1, "last_updated": func.now()},
            )
        )
        await self.session.execute(stmt)
