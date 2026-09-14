"""AI document service - orchestration for the FIN-AI-004 suite (SKY-81/SKY-83).

Core owns the data and the DRAFT->approved lifecycle; the LLM heavy lifting is
relayed to ai-agent (see :mod:`core.features.ai_docs.ai_client`). Every
mutation is recorded on the tenant's audit trail via the shared
:class:`core.core.audit_service.AuditService`.

A5  tax summaries      - relay snapshot -> per-category draft, approve/reject.
A6  document packs     - render branded PDF (DRAFT watermark) -> approve.
A10 audit narration    - relay posted entries for a range -> narrative + risks.
A12 doc Q&A            - relay question to ai-agent's RAG pipeline.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import structlog

from core.core.audit_events import (
    FINANCE_AI_AUDIT_NARRATED,
    FINANCE_AI_DOC_APPROVED,
    FINANCE_AI_DOC_GENERATED,
    FINANCE_AI_TAX_SUMMARY_APPROVED,
    FINANCE_AI_TAX_SUMMARY_GENERATED,
    FINANCE_AI_TAX_SUMMARY_REJECTED,
)
from core.core.audit_service import AuditService
from core.core.exceptions import AiServiceUnavailableError, NotFoundError, ValidationError
from core.features.ai_docs import ai_client as ai_client_mod
from core.features.ai_docs import pdf_renderer, schemas, text_renderer
from core.features.ai_docs.models.ai_doc import ErpAiDocModel
from core.features.ai_docs.models.tax_summary import ErpTaxSummaryModel
from core.features.ai_docs.repository import AiDocRepository

logger = structlog.get_logger("core.finance.ai_docs")


class AiDocService:
    """Business rules for AI-generated finance documents (FIN-AI-004)."""

    def __init__(self, repo: AiDocRepository, audit: AuditService) -> None:
        self._repo = repo
        self._audit = audit

    # ------------------------------------------------------------------ A5
    async def generate_tax_summary(
        self,
        *,
        tenant_id: uuid.UUID,
        period_id: uuid.UUID,
        client: httpx.AsyncClient,
        authorization: str | None,
        tenant_slug: str | None,
    ) -> schemas.TaxSummaryResponse:
        period = await self._repo.get_fiscal_period(tenant_id, period_id)
        if period is None:
            raise NotFoundError(f"Fiscal period {period_id} not found")

        entries = await self._repo.posted_entries_snapshot(
            tenant_id, period.start_date, period.end_date
        )
        if not entries:
            raise ValidationError(
                f"Fiscal period '{period.name}' has no posted entries to summarize"
            )
        period_info = {
            "id": str(period.id),
            "name": period.name,
            "start_date": period.start_date.isoformat(),
            "end_date": period.end_date.isoformat(),
            "is_closed": period.is_closed,
        }
        ai = await ai_client_mod.generate_tax_summary_with_ai(
            client,
            authorization=authorization,
            tenant_slug=tenant_slug,
            period=period_info,
            snapshot={"entries": entries},
        )
        if ai is None:
            raise AiServiceUnavailableError(
                "Tax-summary generation unavailable or no categories returned"
            )

        categories = ai["categories"]
        model_used = str(ai.get("model_used") or "").strip() or "unknown"
        model = await self._repo.create_tax_summary(
            tenant_id=tenant_id,
            period_id=period_id,
            period_name=period.name,
            start_date=period.start_date,
            end_date=period.end_date,
            snapshot_id=period.id,
            snapshot={"entries": entries, "period": period_info},
            categories=categories,
            total_input=Decimal(str(ai.get("total_input") or 0)),
            total_output=Decimal(str(ai.get("total_output") or 0)),
            model_used=model_used,
        )
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=None,
            action=FINANCE_AI_TAX_SUMMARY_GENERATED,
            target=f"tax_summary:{model.id}",
            details={
                "period_id": str(period_id),
                "period_name": period.name,
                "status": "draft",
            },
        )
        text = text_renderer.render_tax_summary_markdown(
            period_name=period.name,
            start_date=period.start_date,
            end_date=period.end_date,
            categories=categories,
            total_input=ai.get("total_input"),
            total_output=ai.get("total_output"),
        )
        await self._index_best_effort(
            tenant_id=tenant_id,
            client=client,
            authorization=authorization,
            tenant_slug=tenant_slug,
            source_ref=f"tax-summary/{model.id}",
            text=text,
            page_title=f"Tax Summary - {period.name}",
        )
        return _tax_summary_response(model)

    async def list_tax_summaries(
        self, tenant_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[schemas.TaxSummaryResponse]:
        models = await self._repo.list_tax_summaries(tenant_id, limit=limit, offset=offset)
        return [_tax_summary_response(m) for m in models]

    async def approve_tax_summary(
        self, tenant_id: uuid.UUID, summary_id: uuid.UUID, user_id: uuid.UUID
    ) -> schemas.TaxSummaryActionResponse:
        model = await self._repo.set_tax_summary_status(tenant_id, summary_id, "approved", user_id)
        if model is None:
            raise NotFoundError(f"Tax summary {summary_id} not found")
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_AI_TAX_SUMMARY_APPROVED,
            target=f"tax_summary:{model.id}",
            details={"period_name": model.period_name},
        )
        return schemas.TaxSummaryActionResponse(id=model.id, status="approved", watermarked=False)

    async def reject_tax_summary(
        self, tenant_id: uuid.UUID, summary_id: uuid.UUID, user_id: uuid.UUID
    ) -> schemas.TaxSummaryActionResponse:
        model = await self._repo.set_tax_summary_status(tenant_id, summary_id, "rejected", user_id)
        if model is None:
            raise NotFoundError(f"Tax summary {summary_id} not found")
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_AI_TAX_SUMMARY_REJECTED,
            target=f"tax_summary:{model.id}",
            details={"period_name": model.period_name},
        )
        return schemas.TaxSummaryActionResponse(id=model.id, status="rejected", watermarked=False)

    # ------------------------------------------------------------------ A6
    async def generate_doc(
        self,
        *,
        tenant_id: uuid.UUID,
        doc_type: str,
        snapshot_id: uuid.UUID,
        snapshot_data: dict[str, Any],
        client: httpx.AsyncClient,
        authorization: str | None,
        tenant_slug: str | None,
    ) -> schemas.AiDocResponse:
        if doc_type not in schemas.AI_DOC_TYPES:
            raise ValueError(f"Unsupported doc_type: {doc_type}")
        version = await self._repo.next_doc_version(tenant_id, doc_type, snapshot_id)
        pdf_bytes = pdf_renderer.render_report_pdf(
            doc_type=doc_type, snapshot_data=snapshot_data, watermarked=True, revision=str(version)
        )
        model = await self._repo.create_doc(
            tenant_id=tenant_id,
            doc_type=doc_type,
            snapshot_id=snapshot_id,
            snapshot_data=snapshot_data,
            version=version,
            pdf_bytes=pdf_bytes,
            watermarked=True,
        )
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=None,
            action=FINANCE_AI_DOC_GENERATED,
            target=f"ai_doc:{model.id}",
            details={"doc_type": doc_type, "version": version, "status": "draft"},
        )
        text = text_renderer.render_report_markdown(
            doc_type=doc_type, snapshot_data=snapshot_data, revision=str(version)
        )
        title = "Profit & Loss" if doc_type == "pnl" else "Balance Sheet"
        await self._index_best_effort(
            tenant_id=tenant_id,
            client=client,
            authorization=authorization,
            tenant_slug=tenant_slug,
            source_ref=f"finance-doc/{model.id}/rev{version}",
            text=text,
            page_title=title,
        )
        return _doc_response(model)

    async def list_docs(
        self,
        tenant_id: uuid.UUID,
        doc_type: str | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[schemas.AiDocResponse]:
        models = await self._repo.list_docs(tenant_id, doc_type, limit=limit, offset=offset)
        return [_doc_response(m) for m in models]

    async def download_doc(self, tenant_id: uuid.UUID, doc_id: uuid.UUID) -> bytes:
        model = await self._repo.get_doc(tenant_id, doc_id)
        if model is None:
            raise NotFoundError(f"AI document {doc_id} not found")
        return model.pdf_bytes or b""

    async def approve_doc(
        self, tenant_id: uuid.UUID, doc_id: uuid.UUID, user_id: uuid.UUID
    ) -> schemas.AiDocActionResponse:
        model = await self._repo.approve_doc(tenant_id, doc_id, user_id)
        if model is None:
            raise NotFoundError(f"AI document {doc_id} not found")
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_AI_DOC_APPROVED,
            target=f"ai_doc:{model.id}",
            details={"doc_type": model.doc_type, "version": model.version},
        )
        return schemas.AiDocActionResponse(
            id=model.id, status="approved", watermarked=False, version=model.version
        )

    # ----------------------------------------------------------------- A10
    async def narrate_audit(
        self,
        *,
        tenant_id: uuid.UUID,
        from_date: date,
        to_date: date,
        client: httpx.AsyncClient,
        authorization: str | None,
        tenant_slug: str | None,
    ) -> schemas.AuditNarrationResponse:
        entries = await self._repo.posted_entries_snapshot(tenant_id, from_date, to_date)
        ai = await ai_client_mod.narrate_audit_with_ai(
            client,
            authorization=authorization,
            tenant_slug=tenant_slug,
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
            entries=entries,
        )
        if ai is None:
            raise AiServiceUnavailableError("Audit narration unavailable")
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=None,
            action=FINANCE_AI_AUDIT_NARRATED,
            target=f"audit_range:{from_date.isoformat()}..{to_date.isoformat()}",
            details={"entries": len(entries)},
        )
        return schemas.AuditNarrationResponse(
            from_date=from_date,
            to_date=to_date,
            narration=str(ai.get("narration") or "").strip(),
            risk_areas=[
                schemas.RiskArea(
                    entry_id=(ra.get("entry_id") if isinstance(ra, dict) else None),
                    risk_type=str(ra.get("risk_type") or "general"),
                    description=str(ra.get("description") or "").strip(),
                    severity=str(ra.get("severity") or "medium").strip(),
                )
                for ra in ai.get("risk_areas") or []
                if isinstance(ra, dict)
            ],
            model_used=str(ai.get("model_used") or "").strip() or "unknown",
        )

    # ----------------------------------------------------------------- A12
    async def answer_question(
        self,
        *,
        tenant_id: uuid.UUID,
        question: str,
        client: httpx.AsyncClient,
        authorization: str | None,
        tenant_slug: str | None,
    ) -> schemas.DocQaAnswer:
        ai = await ai_client_mod.answer_question_with_ai(
            client,
            authorization=authorization,
            tenant_slug=tenant_slug,
            question=question,
        )
        if ai is None:
            raise AiServiceUnavailableError("Document Q&A unavailable")
        return schemas.DocQaAnswer(
            answer=str(ai.get("answer") or "").strip(),
            citations=[
                schemas.DocCitation(
                    source_ref=str(c.get("source_ref") or "").strip(),
                    chunk_text=str(c.get("chunk_text") or "").strip(),
                    score=float(c.get("score") or 0.0),
                )
                for c in ai.get("citations") or []
                if isinstance(c, dict)
            ],
            model_used=str(ai.get("model_used") or "").strip() or "unknown",
        )

    async def _index_best_effort(
        self,
        *,
        tenant_id: uuid.UUID,
        client: httpx.AsyncClient,
        authorization: str | None,
        tenant_slug: str | None,
        source_ref: str,
        text: str,
        page_title: str,
    ) -> None:
        """Push one generated document into RAG so A12 can cite it.

        Best-effort by design: an indexing failure must never roll back or
        block document generation - Q&A simply lags until the next generate.
        """
        try:
            ok = await ai_client_mod.index_finance_doc_in_rag(
                client,
                authorization=authorization,
                tenant_slug=tenant_slug,
                source_ref=source_ref,
                text=text,
                page_title=page_title,
            )
            if not ok:
                logger.warning(
                    "finance_ai_docs.rag_index_refused",
                    tenant_id=str(tenant_id),
                    source_ref=source_ref,
                )
        except Exception:  # best-effort ingest, never block generation
            logger.exception(
                "finance_ai_docs.rag_index_failed",
                tenant_id=str(tenant_id),
                source_ref=source_ref,
            )


def _tax_summary_response(m: ErpTaxSummaryModel) -> schemas.TaxSummaryResponse:
    return schemas.TaxSummaryResponse(
        id=m.id,
        period_id=m.period_id,
        period_name=m.period_name,
        start_date=m.start_date,
        end_date=m.end_date,
        snapshot_id=m.snapshot_id,
        categories=[
            schemas.TaxCategoryLine(
                category=str(c.get("category") or ""),
                detail=str(c.get("detail") or ""),
                input_tax=Decimal(str(c.get("input_tax") or 0)),
                output_tax=Decimal(str(c.get("output_tax") or 0)),
                net=Decimal(str(c.get("net") or 0)),
            )
            for c in (m.categories or [])
            if isinstance(c, dict)
        ],
        total_input=m.total_input,
        total_output=m.total_output,
        status=m.status,
        model_used=m.model_used,
        approved_by_user_id=m.approved_by_user_id,
        approved_at=m.approved_at,
        created_at=m.created_at,
    )


def _doc_response(m: ErpAiDocModel) -> schemas.AiDocResponse:
    return schemas.AiDocResponse(
        id=m.id,
        doc_type=m.doc_type,
        snapshot_id=m.snapshot_id,
        version=m.version,
        status=m.status,
        watermarked=m.watermarked,
        approved_by_user_id=m.approved_by_user_id,
        approved_at=m.approved_at,
        created_at=m.created_at,
    )
