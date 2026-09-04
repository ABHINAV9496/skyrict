"""Core -> ai-agent scoring client for the HR attrition model (Commit 3).

Core proxies ANONYMOUS per-employee feature vectors to ``ai-agent``
``POST /ai/hr/attrition/score`` and maps the returned scores back into
:class:`ScoredRisk` rows for the repository to persist. The employee UUID is
sent as ``employee_ref`` (opaque to ai-agent - it has no HR knowledge).

The caller's ``Authorization`` and tenant slug are relayed so ai-agent can
re-verify the JWT and cross-check the tenant (the same posture as the generic
``/ai`` proxy). transport + non-2xx failures surface as
:class:`AiServiceUnavailableError`, which the service treats as "serve stored
scores as-of" rather than failing the read.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import httpx

from core.core.exceptions import AiServiceUnavailableError
from core.features.ai.proxy import forward_to_ai_agent
from core.features.ai_hr.attrition_repository import FeatureVector, ScoredRisk

_UPSTREAM_PATH = "/ai/hr/attrition/score"


async def score_features(
    client: httpx.AsyncClient,
    *,
    authorization: str | None,
    tenant_slug: str | None,
    features: Sequence[FeatureVector],
) -> list[ScoredRisk]:
    """Score a tenant's employees via ai-agent; abstained employees are absent."""
    payload = {
        "employees": [
            {
                "employee_ref": str(f.employee_id),
                "tenure_years": f.tenure_years,
                "compa_ratio": f.compa_ratio,
                "promotion_gap_months": f.promotion_gap_months,
                "activity_count": f.activity_count,
            }
            for f in features
        ]
    }
    upstream = await forward_to_ai_agent(
        client,
        method="POST",
        upstream_path=_UPSTREAM_PATH,
        authorization=authorization,
        tenant_slug=tenant_slug,
        body=json.dumps(payload).encode("utf-8"),
    )
    if upstream.status_code >= 400:
        raise AiServiceUnavailableError("AI agent attrition scoring failed")

    data = upstream.json()
    by_ref = {f.employee_id: f for f in features}
    scored: list[ScoredRisk] = []
    for entry in data.get("scored", []):
        employee_id = uuid.UUID(entry["employee_ref"])
        feature = by_ref.get(employee_id)
        scored.append(
            ScoredRisk(
                employee_id=employee_id,
                department_id=feature.department_id if feature else None,
                score=float(entry["score"]),
                risk_band=entry["risk_band"],
                confidence=float(entry["confidence"]),
                factors=[dict(f) for f in entry.get("factors", [])],
                model_version=data.get("model_version", ""),
                generated_at=datetime.now(UTC),
            )
        )
    return scored
