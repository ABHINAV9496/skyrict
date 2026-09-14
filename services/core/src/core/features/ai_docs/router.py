"""AI document & tax suite routes (FIN-AI-004, SKY-81/SKY-83).

Permission gates mirror finance automation:
- ``erp.finance.ai.read``  - generate/list tax summaries, audit narration, Q&A
- ``erp.finance.ai.write`` - generate document packs
- ``erp.finance.approve``  - approve tax summaries / document packs

Generation is a DRAFT until an approver confirms; every mutation is
audit-logged by the service. LLM work is relayed to ai-agent with the caller's
JWT + tenant slug; upstream failures surface as ``AiServiceUnavailableError``.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from core.api.deps import get_ai_docs_service, require_permission
from core.core.tenant_resolver import derive_tenant_slug
from core.features.ai.router import get_ai_client
from core.features.ai_docs import schemas
from core.features.ai_docs.service import AiDocService
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/finance/ai", tags=["finance-ai-docs"])

_require_ai_read = require_permission("erp.finance.ai.read")
_require_ai_write = require_permission("erp.finance.ai.write")
_require_approve = require_permission("erp.finance.approve")

_ClientDep = Annotated[httpx.AsyncClient, Depends(get_ai_client)]
_SvcDep = Annotated[AiDocService, Depends(get_ai_docs_service)]
_AiReadUser = Annotated[dict[str, Any], Depends(_require_ai_read)]
_AiWriteUser = Annotated[dict[str, Any], Depends(_require_ai_write)]
_ApproveUser = Annotated[dict[str, Any], Depends(_require_approve)]


def _tenant_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["tenant_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


def _user_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["user_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


def _auth(request: Request) -> tuple[str | None, str | None]:
    return request.headers.get("authorization"), derive_tenant_slug(request)


# ------------------------------------------------------------------ A5: tax
@router.post(
    "/tax-summary/generate",
    response_model=ResponseEnvelope[schemas.TaxSummaryResponse],
)
async def generate_tax_summary(
    body: schemas.TaxSummaryGenerateRequest,
    request: Request,
    current_user: _AiReadUser,
    client: _ClientDep,
    svc: _SvcDep,
) -> ResponseEnvelope[schemas.TaxSummaryResponse]:
    auth, tenant_slug = _auth(request)
    result = await svc.generate_tax_summary(
        tenant_id=_tenant_id(current_user),
        period_id=body.period_id,
        client=client,
        authorization=auth,
        tenant_slug=tenant_slug,
    )
    return ResponseEnvelope(data=result)


@router.get(
    "/tax-summaries",
    response_model=ResponseEnvelope[list[schemas.TaxSummaryResponse]],
)
async def list_tax_summaries(
    current_user: _AiReadUser,
    svc: _SvcDep,
) -> ResponseEnvelope[list[schemas.TaxSummaryResponse]]:
    return ResponseEnvelope(data=await svc.list_tax_summaries(_tenant_id(current_user)))


@router.post(
    "/tax-summaries/{summary_id}/approve",
    response_model=ResponseEnvelope[schemas.TaxSummaryActionResponse],
)
async def approve_tax_summary(
    summary_id: uuid.UUID,
    current_user: _ApproveUser,
    svc: _SvcDep,
) -> ResponseEnvelope[schemas.TaxSummaryActionResponse]:
    result = await svc.approve_tax_summary(
        _tenant_id(current_user), summary_id, _user_id(current_user)
    )
    return ResponseEnvelope(data=result)


@router.post(
    "/tax-summaries/{summary_id}/reject",
    response_model=ResponseEnvelope[schemas.TaxSummaryActionResponse],
)
async def reject_tax_summary(
    summary_id: uuid.UUID,
    current_user: _ApproveUser,
    svc: _SvcDep,
) -> ResponseEnvelope[schemas.TaxSummaryActionResponse]:
    result = await svc.reject_tax_summary(
        _tenant_id(current_user), summary_id, _user_id(current_user)
    )
    return ResponseEnvelope(data=result)


# ------------------------------------------------------------------ A6: docs
@router.post(
    "/docs/generate",
    response_model=ResponseEnvelope[schemas.AiDocResponse],
)
async def generate_doc(
    body: schemas.DocPackGenerateRequest,
    request: Request,
    current_user: _AiWriteUser,
    client: _ClientDep,
    svc: _SvcDep,
) -> ResponseEnvelope[schemas.AiDocResponse]:
    auth, tenant_slug = _auth(request)
    result = await svc.generate_doc(
        tenant_id=_tenant_id(current_user),
        doc_type=body.doc_type,
        snapshot_id=body.snapshot_id,
        snapshot_data=body.snapshot_data,
        client=client,
        authorization=auth,
        tenant_slug=tenant_slug,
    )
    return ResponseEnvelope(data=result)


@router.get(
    "/docs",
    response_model=ResponseEnvelope[list[schemas.AiDocResponse]],
)
async def list_docs(
    current_user: _AiReadUser,
    svc: _SvcDep,
    doc_type: str | None = None,
) -> ResponseEnvelope[list[schemas.AiDocResponse]]:
    return ResponseEnvelope(data=await svc.list_docs(_tenant_id(current_user), doc_type))


@router.get("/docs/{doc_id}/download")
async def download_doc(
    doc_id: uuid.UUID,
    current_user: _AiReadUser,
    svc: _SvcDep,
) -> Response:
    pdf_bytes = await svc.download_doc(_tenant_id(current_user), doc_id)
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.post(
    "/docs/{doc_id}/approve",
    response_model=ResponseEnvelope[schemas.AiDocActionResponse],
)
async def approve_doc(
    doc_id: uuid.UUID,
    current_user: _ApproveUser,
    svc: _SvcDep,
) -> ResponseEnvelope[schemas.AiDocActionResponse]:
    result = await svc.approve_doc(_tenant_id(current_user), doc_id, _user_id(current_user))
    return ResponseEnvelope(data=result)


# ------------------------------------------------------------------ A10
@router.post(
    "/audit-narration",
    response_model=ResponseEnvelope[schemas.AuditNarrationResponse],
)
async def narrate_audit(
    body: schemas.AuditNarrationRequest,
    request: Request,
    current_user: _AiReadUser,
    client: _ClientDep,
    svc: _SvcDep,
) -> ResponseEnvelope[schemas.AuditNarrationResponse]:
    auth, tenant_slug = _auth(request)
    result = await svc.narrate_audit(
        tenant_id=_tenant_id(current_user),
        from_date=body.from_date,
        to_date=body.to_date,
        client=client,
        authorization=auth,
        tenant_slug=tenant_slug,
    )
    return ResponseEnvelope(data=result)


# ------------------------------------------------------------------ A12
@router.post(
    "/doc-qa",
    response_model=ResponseEnvelope[schemas.DocQaAnswer],
)
async def answer_question(
    body: schemas.DocQaRequest,
    request: Request,
    current_user: _AiReadUser,
    client: _ClientDep,
    svc: _SvcDep,
) -> ResponseEnvelope[schemas.DocQaAnswer]:
    auth, tenant_slug = _auth(request)
    result = await svc.answer_question(
        tenant_id=_tenant_id(current_user),
        question=body.question,
        client=client,
        authorization=auth,
        tenant_slug=tenant_slug,
    )
    return ResponseEnvelope(data=result)
