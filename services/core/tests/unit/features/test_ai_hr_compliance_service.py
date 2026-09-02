"""Unit tests for the compliance engine v1 (HR-AI-001, Unit C).

The pure rule engine lives in skyrict_common and is unit-tested there; these
tests exercise the service layer: the L1 aggregate, the L2 per-employee
scoping, the lazy-on-read TTL scan, and the status lifecycle with its audit
events and transition guardrails.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core.features.ai_hr.compliance_repository import ComplianceFindingRow
from core.features.ai_hr.compliance_service import ComplianceService
from core.features.ai_hr.models.compliance_check import ComplianceStatus

pytestmark = pytest.mark.unit

TENANT = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
E1 = uuid.UUID("22222222-2222-2222-2222-222222222222")
E2 = uuid.UUID("33333333-3333-3333-3333-333333333333")
E3 = uuid.UUID("44444444-4444-4444-4444-444444444444")


def _row(
    *,
    check_id: uuid.UUID | None = None,
    employee_id: uuid.UUID | None = E1,
    check_type: str = "document_expiry",
    severity: str = "medium",
    status: str = ComplianceStatus.OPEN,
    owner_rule: str = "compliance_officer",
) -> ComplianceFindingRow:
    return ComplianceFindingRow(
        employee_id=employee_id,
        check_type=check_type,
        severity=severity,
        owner_rule=owner_rule,
        status=status,
        title="Identity document expiring",
        description="Visa document expires soon (20 day(s) remaining).",
        evidence={"doc_type": "visa", "days_left": 20},
        created_at=datetime.now(UTC),
        check_id=check_id or uuid.uuid4(),
    )


class _FakeAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def log(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


class _FakeComplianceRepo:
    def __init__(
        self,
        *,
        latest: datetime | None = None,
        rows: list[ComplianceFindingRow] | None = None,
        stored: list[ComplianceFindingRow] | None = None,
    ) -> None:
        self.latest = latest
        self.rows = rows or []
        self.stored = stored or []
        self.replacements: list[list[ComplianceFindingRow]] = []

    async def latest_generated_at(self, tenant_id: uuid.UUID) -> datetime | None:
        return self.latest

    async def build_compliance_rows(self, tenant_id: uuid.UUID) -> list[ComplianceFindingRow]:
        return list(self.rows)

    async def replace_tenant_findings(
        self, tenant_id: uuid.UUID, rows: list[ComplianceFindingRow]
    ) -> None:
        self.replacements.append(rows)
        self.stored = rows

    async def list_findings(
        self, tenant_id: uuid.UUID, employee_id: uuid.UUID | None = None
    ) -> list[ComplianceFindingRow]:
        if employee_id is not None:
            return [f for f in self.stored if f.employee_id == employee_id]
        return list(self.stored)

    async def get_finding(
        self, tenant_id: uuid.UUID, check_id: uuid.UUID
    ) -> ComplianceFindingRow | None:
        for f in self.stored:
            if f.check_id == check_id:
                return f
        return None

    async def set_status(
        self,
        tenant_id: uuid.UUID,
        check_id: uuid.UUID,
        *,
        status: str,
        owner_user_id: uuid.UUID | None = None,
    ) -> ComplianceFindingRow | None:
        idx = next(
            (i for i, f in enumerate(self.stored) if f.check_id == check_id),
            None,
        )
        if idx is None:
            return None
        current = self.stored[idx]
        updated = ComplianceFindingRow(
            employee_id=current.employee_id,
            check_type=current.check_type,
            severity=current.severity,
            owner_rule=current.owner_rule,
            status=status,
            title=current.title,
            description=current.description,
            evidence=current.evidence,
            created_at=current.created_at,
            check_id=current.check_id,
            owner_user_id=owner_user_id if status == ComplianceStatus.ACKNOWLEDGED else None,
        )
        self.stored[idx] = updated
        return updated


async def test_org_feed_aggregates_types_and_severity() -> None:
    repo = _FakeComplianceRepo(
        latest=datetime.now(UTC),
        stored=[
            _row(check_type="document_expiry", severity="high"),
            _row(
                employee_id=E2,
                check_type="training_overdue",
                severity="medium",
            ),
            _row(
                employee_id=E3,
                check_type="contract_missing_field",
                severity="low",
                owner_rule="hr_admin",
                status=ComplianceStatus.RESOLVED,
            ),
        ],
    )
    svc = ComplianceService(repo, refresh_days=7)
    summary = await svc.org_feed(TENANT)
    assert summary.total_findings == 3
    assert summary.open_findings == 2
    assert summary.by_type == {
        "document_expiry": 1,
        "training_overdue": 1,
        "contract_missing_field": 1,
    }
    assert summary.by_severity == {"high": 1, "medium": 1, "low": 1}
    assert "2 open" in summary.narrative


async def test_employee_findings_scopes_by_employee() -> None:
    repo = _FakeComplianceRepo(
        latest=datetime.now(UTC),
        stored=[
            _row(employee_id=E1),
            _row(employee_id=E2, check_type="training_overdue"),
        ],
    )
    svc = ComplianceService(repo, refresh_days=7)
    assert len(await svc.employee_findings(TENANT, E1)) == 1
    assert len(await svc.employee_findings(TENANT, E2)) == 1


async def test_scan_skipped_when_fresh() -> None:
    repo = _FakeComplianceRepo(latest=datetime.now(UTC), stored=[_row()])
    await ComplianceService(repo, refresh_days=7).org_feed(TENANT)
    assert repo.replacements == []


async def test_scan_runs_when_stale_or_absent() -> None:
    stale = _FakeComplianceRepo(
        latest=datetime.now(UTC) - timedelta(days=8), rows=[_row()]
    )
    await ComplianceService(stale, refresh_days=7).org_feed(TENANT)
    assert len(stale.replacements) == 1

    absent = _FakeComplianceRepo(latest=None, rows=[_row()])
    await ComplianceService(absent, refresh_days=7).org_feed(TENANT)
    assert len(absent.replacements) == 1


async def test_status_open_to_acknowledged_audits() -> None:
    target = _row()
    repo = _FakeComplianceRepo(latest=datetime.now(UTC), stored=[target])
    audit = _FakeAudit()
    svc = ComplianceService(repo, refresh_days=7, audit=audit)
    actor = uuid.uuid4()
    updated = await svc.set_status(
        TENANT, target.check_id, status=ComplianceStatus.ACKNOWLEDGED, actor_user_id=actor
    )
    assert updated.status == ComplianceStatus.ACKNOWLEDGED
    assert updated.owner_user_id == actor
    assert audit.events[0]["action"] == "hr.ai.compliance.acknowledged"
    assert audit.events[0]["target"] == f"compliance:{target.check_id}"


async def test_status_acknowledged_to_resolved_audits() -> None:
    target = _row(status=ComplianceStatus.ACKNOWLEDGED)
    repo = _FakeComplianceRepo(latest=datetime.now(UTC), stored=[target])
    audit = _FakeAudit()
    svc = ComplianceService(repo, refresh_days=7, audit=audit)
    updated = await svc.set_status(
        TENANT, target.check_id, status=ComplianceStatus.RESOLVED, actor_user_id=uuid.uuid4()
    )
    assert updated.status == ComplianceStatus.RESOLVED
    assert audit.events[0]["action"] == "hr.ai.compliance.resolved"


async def test_status_rejects_backwards_or_disallowed_transition() -> None:
    from core.core.exceptions import IllegalStateTransitionError

    resolved = _row(status=ComplianceStatus.RESOLVED)
    repo = _FakeComplianceRepo(latest=datetime.now(UTC), stored=[resolved])
    svc = ComplianceService(repo, refresh_days=7)
    with pytest.raises(IllegalStateTransitionError):
        await svc.set_status(
            TENANT, resolved.check_id, status=ComplianceStatus.ACKNOWLEDGED, actor_user_id=uuid.uuid4()
        )


async def test_status_unknown_status_rejected() -> None:
    from core.core.exceptions import IllegalStateTransitionError

    target = _row()
    repo = _FakeComplianceRepo(latest=datetime.now(UTC), stored=[target])
    svc = ComplianceService(repo, refresh_days=7)
    with pytest.raises(IllegalStateTransitionError):
        await svc.set_status(
            TENANT, target.check_id, status="banana", actor_user_id=uuid.uuid4()
        )


async def test_status_missing_finding_raises_not_found() -> None:
    from core.core.exceptions import NotFoundError

    repo = _FakeComplianceRepo(latest=datetime.now(UTC))
    svc = ComplianceService(repo, refresh_days=7)
    with pytest.raises(NotFoundError):
        await svc.set_status(
            TENANT, uuid.uuid4(), status=ComplianceStatus.RESOLVED, actor_user_id=uuid.uuid4()
        )
