"""/ai/hr/attrition endpoints - model scoring + factor explanations (spec §6).

Authn here (JWT re-verification); authz happens at the core proxy edge before
this is ever reached. This endpoint is deliberately stateless: it accepts
anonymous per-employee feature vectors and returns scores + top-3 factors,
never PII and never an LLM call.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ai_agent.api.deps import get_current_user
from ai_agent.features.attrition.features import EmployeeFeatures
from ai_agent.features.attrition.schemas import (
    FactorOut,
    ScoredEmployeeOut,
    ScoreRequest,
    ScoreResponse,
)
from ai_agent.features.attrition.service import AttritionService

router = APIRouter(prefix="/ai/hr/attrition", tags=["ai-hr-attrition"])


@router.post("/score", response_model=ScoreResponse)
async def score_employees(
    body: ScoreRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> ScoreResponse:
    """Score a tenant's employees and return non-abstaining scores + factors."""
    service = AttritionService()
    features = [
        EmployeeFeatures(
            employee_ref=e.employee_ref,
            tenure_years=e.tenure_years,
            compa_ratio=e.compa_ratio,
            promotion_gap_months=e.promotion_gap_months,
            activity_count=e.activity_count,
        )
        for e in body.employees
    ]
    result = service.score_batch(features)
    return ScoreResponse(
        model_version=result.model_version,
        model_source=result.model_source,
        considered=result.considered,
        abstained=result.abstained,
        scored=[
            ScoredEmployeeOut(
                employee_ref=s.employee_ref,
                score=float(s.score),
                risk_band=s.risk_band,
                confidence=float(s.confidence),
                factors=[
                    FactorOut(
                        feature=f.feature,
                        contribution=float(f.contribution),
                        direction=f.direction,
                    )
                    for f in s.factors
                ],
            )
            for s in result.scored
        ],
    )
