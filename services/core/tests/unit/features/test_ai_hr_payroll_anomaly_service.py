"""Unit tests for the payroll anomaly detector (HR-AI-001, Unit B).

The pure rule engine lives in skyrict_common and is unit-tested there; these
tests exercise the service layer: the L1 aggregate, the L2 per-employee
scoping, the lazy-on-read TTL scan, and the disposition lifecycle with its
audit events and transition guardrails.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core.features.ai_hr.models.payroll_anomaly import AnomalyStatus
from core.features.ai_hr.payroll_anomaly_repository import PayrollAnomaly
from core.features.ai_hr.payroll_anomaly_service import PayrollAnomalyService

pytestmark = pytest.mark.unit

TENANT = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
E1 = uuid.UUID("22222222-2222-2222-2222-222222222222")
E2 = uuid.UUID("33333333-3333-3333-3333-333333333333")
E3 = uuid.UUID("44444444-4444-4444-4444-444444444444")
RUN = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _anomaly(
    *,
    anomaly_id: uuid.UUID | None = None,
    employee_id: uuid.UUID | None = E1,
    anomaly_type: str = "net_pay_delta",
    severity: str = "medium",
    status: str = AnomalyStatus.OPEN,
) -> PayrollAnomaly:
    return PayrollAnomaly(
        run_id=RUN,
        employee_id=employee_id,
        anomaly_type=anomaly_type,
        severity=severity,
        status=status,
        title="Unusual change in net pay",
        description="1.75x swing in PR-2026-04 vs PR-2026-03.",
        evidence={"current_run": "PR-2026-04", "prior_run": "PR-2026-03", "ratio": 1.75},
        created_at=datetime.now(UTC),
        anomaly_id=anomaly_id or uuid.uuid4(),
    )


class _FakeAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def log(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


class _FakePayrollAnomalyRepo:
    def __init__(
        self,
        *,
        latest: datetime | None = None,
        rows: list[PayrollAnomaly] | None = None,
        stored: list[PayrollAnomaly] | None = None,
    ) -> None:
        self.latest = latest
        self.rows = rows or []
        self.stored = stored or []
        self.replacements: list[list[PayrollAnomaly]] = []

    async def latest_generated_at(self, tenant_id: uuid.UUID) -> datetime | None:
        return self.latest

    async def build_anomaly_rows(self, tenant_id: uuid.UUID) -> list[PayrollAnomaly]:
        return list(self.rows)

    async def replace_tenant_anomalies(
        self, tenant_id: uuid.UUID, rows: list[PayrollAnomaly]
    ) -> None:
        self.replacements.append(rows)
        self.stored = rows

    async def list_anomalies(
        self, tenant_id: uuid.UUID, employee_id: uuid.UUID | None = None
    ) -> list[PayrollAnomaly]:
        if employee_id is not None:
            return [a for a in self.stored if a.employee_id == employee_id]
        return list(self.stored)

    async def get_anomaly(self, tenant_id: uuid.UUID, anomaly_id: uuid.UUID) -> PayrollAnomaly | None:
        for a in self.stored:
            if a.anomaly_id == anomaly_id:
                return a
        return None

    async def set_disposition(
        self,
        tenant_id: uuid.UUID,
        anomaly_id: uuid.UUID,
        *,
        status: str,
        actor_user_id: uuid.UUID,
    ) -> PayrollAnomaly | None:
        idx = next(
            (i for i, a in enumerate(self.stored) if a.anomaly_id == anomaly_id),
            None,
        )
        if idx is None:
            return None
        current = self.stored[idx]
        updated = PayrollAnomaly(
            run_id=current.run_id,
            employee_id=current.employee_id,
            anomaly_type=current.anomaly_type,
            severity=current.severity,
            status=status,
            title=current.title,
            description=current.description,
            evidence=current.evidence,
            created_at=current.created_at,
            anomaly_id=current.anomaly_id,
            acknowledged_by=actor_user_id if status == AnomalyStatus.ACKNOWLEDGED else None,
            acknowledged_at=datetime.now(UTC)
            if status == AnomalyStatus.ACKNOWLEDGED
            else None,
        )
        self.stored[idx] = updated
        return updated


async def test_org_feed_aggregates_types_and_severity() -> None:
    repo = _FakePayrollAnomalyRepo(
        latest=datetime.now(UTC),
        stored=[
            _anomaly(anomaly_type="net_pay_delta", severity="medium"),
            _anomaly(
                employee_id=E2,
                anomaly_type="duplicate_account",
                severity="critical",
                status=AnomalyStatus.OPEN,
            ),
            _anomaly(
                employee_id=E3, anomaly_type="ghost_employee", severity="high"
            ),
            _anomaly(
                employee_id=E2,
                anomaly_type="duplicate_account",
                severity="critical",
                status=AnomalyStatus.RESOLVED,
            ),
        ],
    )
    svc = PayrollAnomalyService(repo, refresh_days=7)
    summary = await svc.org_feed(TENANT)
    assert summary.total_anomalies == 4
    assert summary.open_anomalies == 3
    assert summary.by_type == {"net_pay_delta": 1, "duplicate_account": 2, "ghost_employee": 1}
    assert summary.by_severity == {"medium": 1, "critical": 2, "high": 1}
    assert "3 open" in summary.narrative


async def test_employee_anomalies_scopes_by_employee() -> None:
    repo = _FakePayrollAnomalyRepo(
        latest=datetime.now(UTC),
        stored=[_anomaly(employee_id=E1), _anomaly(employee_id=E2, anomaly_type="ghost_employee")],
    )
    svc = PayrollAnomalyService(repo, refresh_days=7)
    assert len(await svc.employee_anomalies(TENANT, E1)) == 1
    assert len(await svc.employee_anomalies(TENANT, E2)) == 1


async def test_scan_skipped_when_fresh() -> None:
    repo = _FakePayrollAnomalyRepo(latest=datetime.now(UTC), stored=[_anomaly()])
    await PayrollAnomalyService(repo, refresh_days=7).org_feed(TENANT)
    assert repo.replacements == []


async def test_scan_runs_when_stale_or_absent() -> None:
    stale = _FakePayrollAnomalyRepo(
        latest=datetime.now(UTC) - timedelta(days=8), rows=[_anomaly()]
    )
    await PayrollAnomalyService(stale, refresh_days=7).org_feed(TENANT)
    assert len(stale.replacements) == 1

    absent = _FakePayrollAnomalyRepo(latest=None, rows=[_anomaly()])
    await PayrollAnomalyService(absent, refresh_days=7).org_feed(TENANT)
    assert len(absent.replacements) == 1


async def test_disposition_open_to_acknowledged_audits() -> None:
    target = _anomaly()
    repo = _FakePayrollAnomalyRepo(latest=datetime.now(UTC), stored=[target])
    audit = _FakeAudit()
    svc = PayrollAnomalyService(repo, refresh_days=7, audit=audit)
    actor = uuid.uuid4()
    updated = await svc.set_disposition(
        TENANT, target.anomaly_id, status=AnomalyStatus.ACKNOWLEDGED, actor_user_id=actor
    )
    assert updated.status == AnomalyStatus.ACKNOWLEDGED
    assert updated.acknowledged_by == actor
    assert audit.events[0]["action"] == "hr.ai.anomaly.acknowledged"
    assert audit.events[0]["target"] == f"payroll_anomaly:{target.anomaly_id}"


async def test_disposition_can_jump_from_acknowledged_to_resolved() -> None:
    target = _anomaly(status=AnomalyStatus.ACKNOWLEDGED)
    repo = _FakePayrollAnomalyRepo(latest=datetime.now(UTC), stored=[target])
    audit = _FakeAudit()
    svc = PayrollAnomalyService(repo, refresh_days=7, audit=audit)
    updated = await svc.set_disposition(
        TENANT, target.anomaly_id, status=AnomalyStatus.RESOLVED, actor_user_id=uuid.uuid4()
    )
    assert updated.status == AnomalyStatus.RESOLVED
    assert audit.events[0]["action"] == "hr.ai.anomaly.resolved"


async def test_disposition_rejects_backwards_or_disallowed_transition() -> None:
    from core.core.exceptions import IllegalStateTransitionError

    resolved = _anomaly(status=AnomalyStatus.RESOLVED)
    repo = _FakePayrollAnomalyRepo(latest=datetime.now(UTC), stored=[resolved])
    svc = PayrollAnomalyService(repo, refresh_days=7)
    with pytest.raises(IllegalStateTransitionError):
        await svc.set_disposition(
            TENANT, resolved.anomaly_id, status=AnomalyStatus.ACKNOWLEDGED, actor_user_id=uuid.uuid4()
        )


async def test_disposition_unknown_status_rejected() -> None:
    from core.core.exceptions import IllegalStateTransitionError

    target = _anomaly()
    repo = _FakePayrollAnomalyRepo(latest=datetime.now(UTC), stored=[target])
    svc = PayrollAnomalyService(repo, refresh_days=7)
    with pytest.raises(IllegalStateTransitionError):
        await svc.set_disposition(
            TENANT, target.anomaly_id, status="banana", actor_user_id=uuid.uuid4()
        )


async def test_disposition_missing_finding_raises_not_found() -> None:
    from core.core.exceptions import NotFoundError

    repo = _FakePayrollAnomalyRepo(latest=datetime.now(UTC))
    svc = PayrollAnomalyService(repo, refresh_days=7)
    with pytest.raises(NotFoundError):
        await svc.set_disposition(
            TENANT, uuid.uuid4(), status=AnomalyStatus.RESOLVED, actor_user_id=uuid.uuid4()
        )
