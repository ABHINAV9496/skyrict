"""Payroll anomaly service (HR-AI-001, Unit B — the payroll anomaly inbox).

Lazy-on-read TTL scan — exactly the leave-anomaly inbox pattern — then:

  - ``org_feed`` (L1, ``erp.hr.ai.read``): aggregate counts by type/severity
    plus a deterministic narrative; never per-person data.
  - ``employee_anomalies`` (L2, ``erp.hr.ai.individual``): one employee's
    findings with stored title/description/evidence.
  - ``set_disposition`` (``erp.hr.ai.acknowledge``): moves a finding along
    ``open -> acknowledged|dismissed|resolved`` and emits an audit event.

The scan rebuilds the tenant inbox from the latest non-void payroll run each
time (replace-tenant regen), so dispositions survive only until the next scan
— mirrors the same tradeoff the leave-anomaly inbox already documents.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from core.core.audit_events import (
    HR_AI_ANOMALY_ACKNOWLEDGED,
    HR_AI_ANOMALY_DISMISSED,
    HR_AI_ANOMALY_RESOLVED,
)
from core.core.exceptions import IllegalStateTransitionError, NotFoundError
from core.features.ai_hr.models.payroll_anomaly import AnomalyStatus
from core.features.ai_hr.payroll_anomaly_repository import PayrollAnomaly
from skyrict_common.ai_hr_rules import AnomalyFinding  # noqa: F401  (re-export surface)

_ANOMALY_DISPOSITION_EVENTS = {
    AnomalyStatus.ACKNOWLEDGED: HR_AI_ANOMALY_ACKNOWLEDGED,
    AnomalyStatus.DISMISSED: HR_AI_ANOMALY_DISMISSED,
    AnomalyStatus.RESOLVED: HR_AI_ANOMALY_RESOLVED,
}

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    AnomalyStatus.OPEN: frozenset(
        {AnomalyStatus.ACKNOWLEDGED, AnomalyStatus.DISMISSED, AnomalyStatus.RESOLVED}
    ),
    AnomalyStatus.ACKNOWLEDGED: frozenset({AnomalyStatus.DISMISSED, AnomalyStatus.RESOLVED}),
    AnomalyStatus.DISMISSED: frozenset(),
    AnomalyStatus.RESOLVED: frozenset(),
}


class AiHrPayrollAnomalyRepositoryPort(Protocol):
    async def latest_generated_at(self, tenant_id: uuid.UUID) -> datetime | None: ...

    async def build_anomaly_rows(self, tenant_id: uuid.UUID) -> list[PayrollAnomaly]: ...

    async def replace_tenant_anomalies(
        self, tenant_id: uuid.UUID, rows: list[PayrollAnomaly]
    ) -> None: ...

    async def list_anomalies(
        self, tenant_id: uuid.UUID, employee_id: uuid.UUID | None = None
    ) -> list[PayrollAnomaly]: ...

    async def get_anomaly(self, tenant_id: uuid.UUID, anomaly_id: uuid.UUID) -> PayrollAnomaly | None: ...

    async def set_disposition(
        self,
        tenant_id: uuid.UUID,
        anomaly_id: uuid.UUID,
        *,
        status: str,
        actor_user_id: uuid.UUID,
    ) -> PayrollAnomaly | None: ...


@dataclass(frozen=True, slots=True)
class PayrollAnomalyOrgSummary:
    """L1 aggregates across the tenant (no per-person data)."""

    total_anomalies: int
    open_anomalies: int
    by_type: dict[str, int]
    by_severity: dict[str, int]
    generated_at: datetime
    narrative: str


class PayrollAnomalyService:
    def __init__(
        self,
        repository: AiHrPayrollAnomalyRepositoryPort,
        refresh_days: int = 7,
        audit=None,
    ) -> None:
        self._repository = repository
        self._refresh_days = refresh_days
        self._audit = audit

    async def _ensure_scan(self, tenant_id: uuid.UUID) -> None:
        latest = await self._repository.latest_generated_at(tenant_id)
        now = datetime.now(UTC)
        stale = latest is None or (now - latest) >= timedelta(days=self._refresh_days)
        if stale:
            rows = await self._repository.build_anomaly_rows(tenant_id)
            await self._repository.replace_tenant_anomalies(tenant_id, rows)

    async def org_feed(self, tenant_id: uuid.UUID) -> PayrollAnomalyOrgSummary:
        await self._ensure_scan(tenant_id)
        anomalies = await self._repository.list_anomalies(tenant_id)
        return self._build_summary(anomalies)

    async def employee_anomalies(
        self, tenant_id: uuid.UUID, employee_id: uuid.UUID
    ) -> list[PayrollAnomaly]:
        await self._ensure_scan(tenant_id)
        return await self._repository.list_anomalies(tenant_id, employee_id=employee_id)

    async def set_disposition(
        self,
        tenant_id: uuid.UUID,
        anomaly_id: uuid.UUID,
        *,
        status: str,
        actor_user_id: uuid.UUID,
    ) -> PayrollAnomaly:
        """Apply a disposition transition and record it in the audit log."""
        if status not in _ANOMALY_DISPOSITION_EVENTS:
            raise IllegalStateTransitionError(
                f"unknown disposition '{status}' for payroll anomaly"
            )
        await self._ensure_scan(tenant_id)
        current = await self._repository.get_anomaly(tenant_id, anomaly_id)
        if current is None:
            raise NotFoundError(f"no payroll anomaly {anomaly_id}")
        if status not in _ALLOWED_TRANSITIONS.get(current.status, frozenset()):
            raise IllegalStateTransitionError(
                f"cannot move payroll anomaly {anomaly_id} from "
                f"'{current.status}' to '{status}'"
            )
        updated = await self._repository.set_disposition(
            tenant_id,
            anomaly_id,
            status=status,
            actor_user_id=actor_user_id,
        )
        if updated is None:
            raise NotFoundError(f"no payroll anomaly {anomaly_id}")
        if self._audit is not None:
            await self._audit.log(
                action=_ANOMALY_DISPOSITION_EVENTS[status],
                target=f"payroll_anomaly:{anomaly_id}",
                tenant_id=str(tenant_id),
                user_id=str(actor_user_id),
                details={"from": current.status, "to": status},
            )
        return updated

    @staticmethod
    def _build_summary(
        anomalies: Sequence[PayrollAnomaly],
    ) -> PayrollAnomalyOrgSummary:
        by_type = Counter(a.anomaly_type for a in anomalies)
        by_severity = Counter(a.severity for a in anomalies)
        open_count = sum(1 for a in anomalies if a.status == AnomalyStatus.OPEN)
        narrative = (
            f"{open_count} open payroll anomaly(-ies) across "
            f"{by_type.get('net_pay_delta', 0)} net-pay swings, "
            f"{by_type.get('duplicate_account', 0)} shared accounts, "
            f"{by_type.get('ghost_employee', 0)} ghost payouts, "
            f"{by_severity.get('critical', 0)} critical."
        )
        return PayrollAnomalyOrgSummary(
            total_anomalies=len(anomalies),
            open_anomalies=open_count,
            by_type=dict(by_type),
            by_severity=dict(by_severity),
            generated_at=anomalies[0].created_at if anomalies else datetime.now(UTC),
            narrative=narrative,
        )


__all__ = [
    "AiHrPayrollAnomalyRepositoryPort",
    "PayrollAnomaly",
    "PayrollAnomalyOrgSummary",
    "PayrollAnomalyService",
]
