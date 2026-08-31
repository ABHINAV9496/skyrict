"""/ai/finance/account-suggest endpoint — LLM account-code suggestion (SKY-56).

Authentication happens here (JWT re-verification); authorization happens
upstream at the core monolith proxy (``erp.finance.read``) before this is
ever reached, matching the narrator/attrition posture. Stateless: accepts a
description + tenant chart-of-accounts and returns the LLM's best account,
or an empty/no-match suggestion on abstention.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ai_agent.api.deps import get_current_user
from ai_agent.features.account_suggest.schemas import AccountOption, SuggestRequest
from ai_agent.features.account_suggest.suggest import suggest


class AccountOptionIn(BaseModel):
    code: str
    name: str


class SuggestPayload(BaseModel):
    description: str
    accounts: list[AccountOptionIn]


class SuggestResponse(BaseModel):
    suggested_code: str
    suggested_name: str
    confidence: float
    reasoning: str
    model_used: str


router = APIRouter(prefix="/ai/finance/account-suggest", tags=["ai-finance"])


@router.post("", response_model=SuggestResponse)
async def suggest_account_code(
    body: SuggestPayload,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    request: Request,
) -> SuggestResponse:
    """Suggest a chart-of-accounts code for a transaction description."""
    req = SuggestRequest(
        description=body.description,
        accounts=[AccountOption(code=a.code, name=a.name) for a in body.accounts],
    )
    result = await suggest(request.app.state.llm_router, req)
    if result is None:
        return SuggestResponse(
            suggested_code="", suggested_name="", confidence=0.0, reasoning="", model_used=""
        )
    return SuggestResponse(
        suggested_code=result.suggested_code,
        suggested_name=result.suggested_name,
        confidence=result.confidence,
        reasoning=result.reasoning,
        model_used=result.model_used,
    )
