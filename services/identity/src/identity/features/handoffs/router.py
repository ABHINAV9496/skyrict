"""Handoff endpoints - issue and redeem single-use onboarding handoff tokens.

These endpoints are part of the pre-auth wizard surface (the wizard hands off
to the BFF before a session exists), so they are deliberately unauthenticated
and bound to an opaque, expiring, single-use token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from identity.api.deps import get_handoff_service
from identity.features.handoffs.schemas import (
    HandoffIssueRequest,
    HandoffIssueResponse,
    HandoffRedeemRequest,
    HandoffRedeemResponse,
)
from identity.features.handoffs.service import HandoffService
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/handoffs", tags=["handoffs"])


@router.post("", response_model=ResponseEnvelope[HandoffIssueResponse])
async def issue_handoff(
    body: HandoffIssueRequest,
    handoff_svc: HandoffService = Depends(get_handoff_service),
) -> ResponseEnvelope[HandoffIssueResponse]:
    """Persist an in-flight payload and return its single-use token."""
    handoff, token = await handoff_svc.issue(purpose=body.purpose, payload=body.payload)
    assert handoff.id is not None
    return ResponseEnvelope(
        data=HandoffIssueResponse(
            id=handoff.id,
            token=token,
            expires_at=handoff.expires_at,
        ),
        message="Handoff issued",
    )


@router.post("/redeem", response_model=ResponseEnvelope[HandoffRedeemResponse])
async def redeem_handoff(
    body: HandoffRedeemRequest,
    handoff_svc: HandoffService = Depends(get_handoff_service),
) -> ResponseEnvelope[HandoffRedeemResponse]:
    """Consume a single-use token and resume the in-flight payload."""
    handoff = await handoff_svc.redeem(token=body.token, purpose=body.purpose)
    assert handoff.id is not None
    return ResponseEnvelope(
        data=HandoffRedeemResponse(
            id=handoff.id,
            purpose=handoff.purpose,
            payload=handoff.payload,
            expires_at=handoff.expires_at,
        ),
        message="Handoff redeemed",
    )
