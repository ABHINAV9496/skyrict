"""/ai/finance endpoints — LLM account-code suggestion, draft entry, anomaly narration, reminders.

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
from ai_agent.features.account_suggest.suggest import (
    draft_entry,
    draft_reminder,
    narrate_anomaly,
    suggest,
)


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
    amount: float | None = None
    side: str = "debit"
    contra_code: str = ""
    contra_name: str = ""


class DraftLineResponse(BaseModel):
    account_code: str
    account_name: str
    amount: float
    side: str
    description: str = ""


class DraftEntryResponse(BaseModel):
    lines: list[DraftLineResponse]
    explanation: str
    confidence: float
    reasoning: str = ""
    model_used: str = ""


class DraftEntryPayload(BaseModel):
    description: str
    accounts: list[AccountOptionIn]


class AnomalyNarratePayload(BaseModel):
    anomaly_type: str
    description: str
    severity: str


class AnomalyNarrateResponse(BaseModel):
    narration: str
    model_used: str = ""


class ReminderDraftPayload(BaseModel):
    customer_name: str | None = None
    invoice_number: str
    amount: float
    days_overdue: int
    tone: str  # "polite" | "firm" | "final"


class ReminderDraftResponse(BaseModel):
    subject: str
    body: str
    tone: str
    model_used: str = ""


router = APIRouter(prefix="/ai/finance", tags=["ai-finance"])


@router.post("/account-suggest", response_model=SuggestResponse)
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
        amount=result.amount,
        side=result.side,
        contra_code=result.contra_code,
        contra_name=result.contra_name,
    )


@router.post("/draft-entry", response_model=DraftEntryResponse)
async def draft_journal_entry(
    body: DraftEntryPayload,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    request: Request,
) -> DraftEntryResponse:
    """Draft a multi-line journal entry from a plain-English description."""
    req = SuggestRequest(
        description=body.description,
        accounts=[AccountOption(code=a.code, name=a.name) for a in body.accounts],
    )
    result = await draft_entry(request.app.state.llm_router, req)
    if result is None:
        return DraftEntryResponse(lines=[], explanation="", confidence=0.0)
    return DraftEntryResponse(
        lines=[
            DraftLineResponse(
                account_code=line.account_code,
                account_name=line.account_name,
                amount=line.amount,
                side=line.side,
                description=line.description,
            )
            for line in result.lines
        ],
        explanation=result.explanation,
        confidence=result.confidence,
        reasoning=result.reasoning,
        model_used=result.model_used,
    )


@router.post("/anomalies/narrate", response_model=AnomalyNarrateResponse)
async def narrate_anomaly_endpoint(
    body: AnomalyNarratePayload,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    request: Request,
) -> AnomalyNarrateResponse:
    """Generate a plain-English narration of a finance anomaly."""
    result = await narrate_anomaly(
        request.app.state.llm_router,
        anomaly_type=body.anomaly_type,
        description=body.description,
        severity=body.severity,
    )
    if result is None:
        return AnomalyNarrateResponse(narration="", model_used="")
    return AnomalyNarrateResponse(
        narration=result["narration"],
        model_used=result.get("model_used", ""),
    )


@router.post("/reminders/draft", response_model=ReminderDraftResponse)
async def draft_reminder_endpoint(
    body: ReminderDraftPayload,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    request: Request,
) -> ReminderDraftResponse:
    """Draft a payment reminder email for an overdue invoice."""
    result = await draft_reminder(
        request.app.state.llm_router,
        customer_name=body.customer_name,
        invoice_number=body.invoice_number,
        amount=body.amount,
        days_overdue=body.days_overdue,
        tone=body.tone,
    )
    if result is None:
        return ReminderDraftResponse(subject="", body="", tone=body.tone)
    return ReminderDraftResponse(
        subject=result["subject"],
        body=result["body"],
        tone=result["tone"],
        model_used=result.get("model_used", ""),
    )
