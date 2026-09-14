"""Unit tests for the CRM anomaly scan service (SKY-91).

The rules themselves are pure and covered by ``test_crm_anomaly_rules``; these
tests cover the scan orchestration on top: closed-deal exclusion, persistence,
per-(opportunity, rule) deduplication, audit emission, and the per-scan cap.
Timestamps are built relative to real UTC time because ``detect_all`` reads
``datetime.now(UTC)`` internally (the rules' documented convention).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from ai_agent.core.audit_events import AI_CRM_ANOMALY_DETECTED
from ai_agent.features.anomalies.crm_scan import (
    _MAX_FINDINGS_PER_SCAN,
    CrmAnomalyScanService,
)
from ai_agent.features.crm.gateway import OpportunityRef

TENANT_ID = uuid.uuid4()


def _now() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


def _opportunity(*, stage: str = "proposal") -> OpportunityRef:
    now = _now()
    return OpportunityRef(
        id=uuid.uuid4(),
        stage=stage,
        probability=40,
        has_amount=True,
        created_at=now - timedelta(days=60),
        owner_id=uuid.uuid4(),
        # Recently moved + far close date => only missing_next_activity fires.
        last_stage_change_at=now,
        expected_close_date=date.today() + timedelta(days=180),
        display_name="Acme Renewal",
    )


class _FakeGateway:
    def __init__(
        self,
        opportunities: list[OpportunityRef],
        activities: dict[uuid.UUID, list[object]] | None = None,
    ) -> None:
        self._opportunities = opportunities
        self._activities = activities or {}
        self.activity_calls: list[uuid.UUID] = []

    async def list_opportunities(self) -> list[OpportunityRef]:
        return self._opportunities

    async def list_activities_for_entity(
        self, *, entity_type: str, entity_id: uuid.UUID
    ) -> list[object]:
        assert entity_type == "opportunity"
        self.activity_calls.append(entity_id)
        return self._activities.get(entity_id, [])


class _FakeRepo:
    def __init__(self, *, open_counts: dict[tuple[uuid.UUID, str], int] | None = None) -> None:
        self._open_counts = open_counts or {}
        self.created: list[dict[str, object]] = []

    async def open_crm_anomaly_count_for_opportunity_and_rule(
        self, *, tenant_id: uuid.UUID, opportunity_id: uuid.UUID, rule_id: str
    ) -> int:
        assert tenant_id == TENANT_ID
        return self._open_counts.get((opportunity_id, rule_id), 0)

    async def create_crm_anomaly(
        self,
        *,
        tenant_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        rule_id: str,
        severity: str,
        title: str,
        description: str,
        context: dict[str, object],
    ) -> SimpleNamespace:
        assert tenant_id == TENANT_ID
        self.created.append(
            {
                "opportunity_id": opportunity_id,
                "rule_id": rule_id,
                "severity": severity,
                "title": title,
                "description": description,
                "context": context,
            }
        )
        return SimpleNamespace(id=uuid.uuid4())


class _FakeAudit:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def log(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


def _service(
    *,
    opportunities: list[OpportunityRef],
    repo: _FakeRepo | None = None,
    activities: dict[uuid.UUID, list[object]] | None = None,
) -> tuple[CrmAnomalyScanService, _FakeGateway, _FakeRepo, _FakeAudit]:
    gateway = _FakeGateway(opportunities, activities)
    repo = repo or _FakeRepo()
    audit = _FakeAudit()
    service = CrmAnomalyScanService(
        gateway=gateway,  # type: ignore[arg-type]
        repo=repo,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
    )
    return service, gateway, repo, audit


class TestClosedDeals:
    async def test_won_and_lost_opportunities_are_never_scanned(self) -> None:
        won = _opportunity(stage="won")
        lost = _opportunity(stage="lost")
        service, gateway, repo, audit = _service(opportunities=[won, lost])

        report = await service.run_scan(tenant_id=TENANT_ID)

        assert report.scanned_opportunities == 0
        assert gateway.activity_calls == []
        assert repo.created == []
        assert audit.calls == []


class TestDetection:
    async def test_persists_new_finding_and_emits_audit(self) -> None:
        opp = _opportunity()
        service, _, repo, audit = _service(opportunities=[opp])

        report = await service.run_scan(tenant_id=TENANT_ID)

        assert report.scanned_opportunities == 1
        assert report.detected == 1
        assert report.duplicates_skipped == 0
        assert repo.created == [
            {
                "opportunity_id": opp.id,
                "rule_id": "missing_next_activity",
                "severity": "critical",
                "title": "No activity on this deal",
                "description": repo.created[0]["description"],
                "context": {"days_since_last_activity": None},
            }
        ]
        assert len(audit.calls) == 1
        assert audit.calls[0]["action"] == AI_CRM_ANOMALY_DETECTED
        assert audit.calls[0]["user_id"] is None
        assert audit.calls[0]["input_payload"] == {"opportunity_id": str(opp.id)}

    async def test_open_anomaly_suppresses_redetection(self) -> None:
        opp = _opportunity()
        repo = _FakeRepo(open_counts={(opp.id, "missing_next_activity"): 1})
        service, _, repo, audit = _service(opportunities=[opp], repo=repo)

        report = await service.run_scan(tenant_id=TENANT_ID)

        assert report.detected == 0
        assert report.duplicates_skipped == 1
        assert repo.created == []
        assert audit.calls == []

    async def test_scan_cap_bounds_new_findings(self) -> None:
        opportunities = [_opportunity() for _ in range(_MAX_FINDINGS_PER_SCAN + 5)]
        service, _, repo, _ = _service(opportunities=opportunities)

        report = await service.run_scan(tenant_id=TENANT_ID)

        assert report.detected == _MAX_FINDINGS_PER_SCAN
        assert len(repo.created) == _MAX_FINDINGS_PER_SCAN
