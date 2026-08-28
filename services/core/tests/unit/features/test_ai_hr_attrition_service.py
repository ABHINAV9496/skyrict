"""Unit tests for the attrition service: lazy TTL + acknowledge (Commit 3).

Pure unit tests with fakes for the attrition repository, the ai-agent scorer
port, the L1 repository, and the audit service — no database, no network.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from core.core.audit_events import HR_AI_RISK_ACKNOWLEDGED
from core.core.exceptions import AiServiceUnavailableError
from core.features.ai_hr.attrition_repository import FeatureVector, ScoredRisk
from core.features.ai_hr.service import AiHrService
from skyrict_common.exceptions import NotFoundError

pytestmark = pytest.mark.unit

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
EMP = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _FakeL1Repo:
    """Stub for the L1 aggregate repository (not exercised by these tests)."""

    async def total_headcount(self, tenant_id: uuid.UUID) -> int:
        return 0

    async def headcount_trend(self, tenant_id: uuid.UUID, months: int = 12):
        return []

    async def department_distribution(self, tenant_id: uuid.UUID):
        return []

    async def tenure_bands(self, tenant_id: uuid.UUID):
        return []


class _FakeAttritionRepo:
    def __init__(
        self,
        *,
        latest: datetime | None,
        features: list[FeatureVector] | None = None,
        stored: list[ScoredRisk] | None = None,
        score_lookup: ScoredRisk | None = None,
    ) -> None:
        self.latest = latest
        self.features = features or []
        self.stored = stored or []
        self.score_lookup = score_lookup
        self.upserts: list[tuple[uuid.UUID, list[ScoredRisk]]] = []
        self.acknowledged_rows: list[uuid.UUID] = []

    async def latest_generated_at(self, tenant_id: uuid.UUID) -> datetime | None:
        return self.latest

    async def build_feature_vectors(self, tenant_id: uuid.UUID) -> list[FeatureVector]:
        return self.features

    async def upsert_scores(self, tenant_id: uuid.UUID, scored) -> None:
        self.upserts.append((tenant_id, list(scored)))

    async def list_scores(self, tenant_id: uuid.UUID) -> list[ScoredRisk]:
        return self.stored

    async def get_score(self, tenant_id: uuid.UUID, employee_id: uuid.UUID) -> ScoredRisk | None:
        return self.score_lookup

    async def acknowledge_score(
        self,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
    ) -> ScoredRisk | None:
        if self.score_lookup is None:
            return None
        # Simulate the same-row persistence by returning the (now acknowledged) row.
        self.acknowledged_rows.append(employee_id)
        return replace(
            self.score_lookup,
            acknowledged=True,
            acknowledged_by=actor_user_id,
            acknowledged_at=datetime.now(UTC),
        )


class _FakeAudit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def log(self, **kwargs) -> None:
        self.events.append(kwargs)


class _RecordingScorer:
    def __init__(self, result: list[ScoredRisk] | None = None, raise_error: bool = False) -> None:
        self.result = result or []
        self.raise_error = raise_error
        self.calls = 0

    async def score(self, tenant_id: uuid.UUID, features) -> list[ScoredRisk]:
        self.calls += 1
        if self.raise_error:
            raise AiServiceUnavailableError("ai-agent down")
        return self.result


def _feature() -> FeatureVector:
    return FeatureVector(
        employee_id=EMP,
        department_id=None,
        tenure_years=1.0,
        compa_ratio=0.8,
        promotion_gap_months=18.0,
        activity_count=1.0,
    )


def _risk() -> ScoredRisk:
    return ScoredRisk(
        employee_id=EMP,
        department_id=None,
        score=0.9,
        risk_band="high",
        confidence=0.98,
        factors=[],
        model_version="v1-gbc-2026-08",
        generated_at=datetime.now(UTC),
    )


def _service(
    attrition: _FakeAttritionRepo, audit: _FakeAudit, refresh_days: int = 7
) -> AiHrService:
    return AiHrService(
        repository=_FakeL1Repo(),
        attrition_repository=attrition,
        audit=audit,
        attrition_refresh_days=refresh_days,
    )


async def test_attrition_refreshes_when_no_scores_stored() -> None:
    risk = _risk()
    repo = _FakeAttritionRepo(latest=None, features=[_feature()])
    audit = _FakeAudit()
    scorer = _RecordingScorer(result=[risk])
    repo.stored = [risk]

    svc = _service(repo, audit)
    result = await svc.attrition(TENANT, scorer=scorer)

    assert scorer.calls == 1
    assert repo.upserts == [(TENANT, [risk])]
    assert result == [risk]


async def test_attrition_serves_fresh_scores_without_rescoring() -> None:
    risk = _risk()
    repo = _FakeAttritionRepo(latest=datetime.now(UTC) - timedelta(days=1), stored=[risk])
    audit = _FakeAudit()
    scorer = _RecordingScorer(result=[_risk()])

    svc = _service(repo, audit)
    result = await svc.attrition(TENANT, scorer=scorer)

    assert scorer.calls == 0
    assert result == [risk]


async def test_attrition_rescores_when_latest_is_stale() -> None:
    repo = _FakeAttritionRepo(
        latest=datetime.now(UTC) - timedelta(days=8),
        features=[_feature()],
        stored=[_risk()],
    )
    audit = _FakeAudit()
    scorer = _RecordingScorer(result=[_risk()])

    svc = _service(repo, audit)
    await svc.attrition(TENANT, scorer=scorer)

    assert scorer.calls == 1


async def test_attrition_falls_back_to_stored_when_scorer_fails() -> None:
    risk = _risk()
    repo = _FakeAttritionRepo(latest=None, features=[_feature()], stored=[risk])
    audit = _FakeAudit()
    scorer = _RecordingScorer(raise_error=True)

    svc = _service(repo, audit)
    result = await svc.attrition(TENANT, scorer=scorer)

    assert result == [risk]
    # The failed score was never persisted.
    assert repo.upserts == []


async def test_acknowledge_persists_row_and_audits() -> None:
    repo = _FakeAttritionRepo(latest=datetime.now(UTC), score_lookup=_risk(), stored=[_risk()])
    audit = _FakeAudit()
    actor = uuid.uuid4()

    svc = _service(repo, audit)
    scored = await svc.acknowledge(TENANT, EMP, actor_user_id=actor)

    # Persisted on the row, not just logged.
    assert repo.acknowledged_rows == [EMP]
    assert scored.acknowledged is True
    assert scored.acknowledged_by == actor
    assert audit.events == [
        {
            "action": HR_AI_RISK_ACKNOWLEDGED,
            "target": f"employee:{EMP}",
            "tenant_id": TENANT,
            "user_id": actor,
        }
    ]


async def test_acknowledge_raises_not_found_when_no_score() -> None:
    repo = _FakeAttritionRepo(latest=datetime.now(UTC), score_lookup=None)
    audit = _FakeAudit()

    svc = _service(repo, audit)
    with pytest.raises(NotFoundError):
        await svc.acknowledge(TENANT, EMP, actor_user_id=uuid.uuid4())
    assert repo.acknowledged_rows == []
    assert audit.events == []
