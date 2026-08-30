"""L1 aggregate service — composes repositories and builds deterministic narratives.

Narratives (spec §5) are rule-based templates over the aggregate numbers, not
LLM output. They are fast, deterministic, and unit-testable.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from core.core.audit_events import HR_AI_RISK_ACKNOWLEDGED
from core.core.exceptions import AiServiceUnavailableError
from core.features.ai_hr.attrition_repository import FeatureVector, ScoredRisk
from core.features.ai_hr.ports import (
    AiHrAttritionRepositoryPort,
    AiHrRepositoryPort,
)
from core.features.ai_hr.repository import (
    DepartmentCount,
    HeadcountPoint,
    Overview,
    TenureBand,
    TenureSummary,
)
from core.features.hr.repository import HrRepository
from skyrict_common.exceptions import NotFoundError

if TYPE_CHECKING:
    from core.core.audit_service import AuditService


class AttritionScorerPort(Protocol):
    """Scores a tenant's feature vectors, dropping abstained employees."""

    async def score(
        self,
        tenant_id: uuid.UUID,
        features: Sequence[FeatureVector],
    ) -> list[ScoredRisk]: ...


def _resolve_ref_date(scored: Sequence[ScoredRisk]) -> datetime | None:
    return scored[0].generated_at if scored else None


def _format_pct(part: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{round(part / total * 100, 1)}%"


def _trend_narrative(trend: list[HeadcountPoint], total: int) -> str:
    if not trend:
        return f"Headcount is {total} across the tenant."
    # Trend is returned newest-first; show the most recent month's hires.
    latest = trend[0]
    return f"Headcount is {total}; the latest month ({latest.month:02d}-{latest.year}) saw {latest.hires} new hire(s)."


def _dept_narrative(departments: list[DepartmentCount], total: int) -> str:
    if not departments:
        return ""
    top = departments[0]
    return f"Largest team is {top.department_name} ({top.count}, {_format_pct(top.count, total)})."


def _tenure_narrative(bands: list[TenureBand], total: int) -> str:
    if not bands:
        return ""
    top = max(bands, key=lambda b: b.count)
    return f"Tenure is concentrated at {top.band} years ({_format_pct(top.count, total)})."


class AiHrService:
    """Read service for the L1 HR aggregates plus the attrition feature."""

    def __init__(
        self,
        repository: AiHrRepositoryPort,
        hr_repository: HrRepository | None = None,
        attrition_repository: AiHrAttritionRepositoryPort | None = None,
        audit: AuditService | None = None,
        attrition_refresh_days: int = 7,
    ) -> None:
        self._repository = repository
        self._hr_repository = hr_repository
        self._attrition_repository = attrition_repository
        self._audit = audit
        self._attrition_refresh_days = attrition_refresh_days

    @property
    def _attrition(self) -> AiHrAttritionRepositoryPort:
        if self._attrition_repository is None:
            raise RuntimeError("attrition repository is not wired into AiHrService")
        return self._attrition_repository

    @property
    def _audit_service(self) -> AuditService:
        if self._audit is None:
            raise RuntimeError("audit service is not wired into AiHrService")
        return self._audit

    async def overview(self, tenant_id: uuid.UUID, months: int = 12) -> Overview:
        total, trend, departments, bands = await self._gather(tenant_id, months)
        narrative = (
            f"{_trend_narrative(trend, total)} "
            f"{_dept_narrative(departments, total)} "
            f"{_tenure_narrative(bands, total)}"
        ).strip()
        return Overview(
            total_headcount=total,
            trend=trend,
            departments=departments,
            tenure_bands=bands,
            generated_at=datetime.now(UTC),
            narrative=narrative,
        )

    async def tenure(self, tenant_id: uuid.UUID) -> TenureSummary:
        total = await self._repository.total_headcount(tenant_id)
        bands = await self._repository.tenure_bands(tenant_id)
        return TenureSummary(
            total_headcount=total,
            bands=bands,
            generated_at=datetime.now(UTC),
            narrative=_tenure_narrative(bands, total),
        )

    async def attrition(
        self,
        tenant_id: uuid.UUID,
        *,
        scorer: AttritionScorerPort,
    ) -> list[ScoredRisk]:
        """Lazy-on-read TTL refresh, then return the current run's scores.

        Serves **stored** scores and only re-scores (via ``scorer``, which
        proxies to ai-agent) when none exist or the latest ``generated_at`` is
        older than the refresh interval (spec §6). A failed re-score degrades
        to the stored scores instead of failing the read, so the dashboard
        always renders with its "as of" label.
        """
        latest = await self._attrition.latest_generated_at(tenant_id)
        now = datetime.now(UTC)
        stale = latest is None or (now - latest) >= timedelta(days=self._attrition_refresh_days)
        if stale:
            try:
                features = await self._attrition.build_feature_vectors(tenant_id)
                scored = await scorer.score(tenant_id, features)
                await self._attrition.upsert_scores(tenant_id, scored)
            except (AiServiceUnavailableError, ValueError):
                pass  # serve whatever is already stored, as-of
        return await self._attrition.list_scores(tenant_id)

    async def acknowledge(
        self,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
    ) -> ScoredRisk:
        """Persist a manager's acknowledgement, then audit it."""
        score = await self._attrition.acknowledge_score(
            tenant_id, employee_id, actor_user_id=actor_user_id
        )
        if score is None:
            raise NotFoundError(f"no attrition score for employee {employee_id}")
        await self._audit_service.log(
            action=HR_AI_RISK_ACKNOWLEDGED,
            target=f"employee:{employee_id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
        )
        return score

    async def _gather(
        self,
        tenant_id: uuid.UUID,
        months: int,
    ) -> tuple[int, list[HeadcountPoint], list[DepartmentCount], list[TenureBand]]:
        total = await self._repository.total_headcount(tenant_id)
        trend = await self._repository.headcount_trend(tenant_id, months)
        departments = await self._repository.department_distribution(tenant_id)
        bands = await self._repository.tenure_bands(tenant_id)
        return total, trend, departments, bands
