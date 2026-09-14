"""AI document feature repository - DB access for FIN-AI-004.

The feature's only DB-touching code. Owns CRUD + the DRAFT/approve status
transitions for ``erp_ai_documents`` and ``erp_tax_summaries`` (tenant-scoped
explcitly, matching the finance repository's contract under RLS). Returns ORM
models; the service maps them to the response schemas.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.value_objects import EntryStatus
from core.features.ai_docs.models.ai_doc import ErpAiDocModel
from core.features.ai_docs.models.tax_summary import ErpTaxSummaryModel
from core.features.finance.models.chart_of_account import ErpChartOfAccountModel
from core.features.finance.models.fiscal_period import ErpFiscalPeriodModel
from core.features.finance.models.journal_entry import ErpJournalEntryModel
from core.features.finance.models.journal_line import ErpJournalLineModel


class AiDocRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # ------------------------------------------------------- finance reads
    async def get_fiscal_period(
        self, tenant_id: uuid.UUID, period_id: uuid.UUID
    ) -> ErpFiscalPeriodModel | None:
        result = await self._db.execute(
            select(ErpFiscalPeriodModel).where(
                ErpFiscalPeriodModel.tenant_id == tenant_id,
                ErpFiscalPeriodModel.id == period_id,
            )
        )
        return result.scalar_one_or_none()

    async def posted_entries_snapshot(
        self, tenant_id: uuid.UUID, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Posted journal entries (with lines + account refs) for a period."""
        entry_rows = await self._db.execute(
            select(
                ErpJournalEntryModel.id,
                ErpJournalEntryModel.entry_date,
                ErpJournalEntryModel.memo,
                ErpJournalEntryModel.source,
                ErpJournalEntryModel.source_ref,
                ErpJournalEntryModel.posted_at,
            )
            .where(
                ErpJournalEntryModel.tenant_id == tenant_id,
                ErpJournalEntryModel.status == EntryStatus.POSTED,
                ErpJournalEntryModel.entry_date >= start_date,
                ErpJournalEntryModel.entry_date <= end_date,
            )
            .order_by(ErpJournalEntryModel.entry_date, ErpJournalEntryModel.created_at)
        )
        entries = [dict(row._mapping) for row in entry_rows.all()]
        if not entries:
            return []
        entry_ids = [e["id"] for e in entries]

        line_rows = await self._db.execute(
            select(
                ErpJournalLineModel.entry_id,
                ErpChartOfAccountModel.code,
                ErpChartOfAccountModel.name,
                ErpChartOfAccountModel.account_type,
                ErpJournalLineModel.debit,
                ErpJournalLineModel.credit,
            )
            .join(
                ErpChartOfAccountModel,
                (ErpChartOfAccountModel.tenant_id == ErpJournalLineModel.tenant_id)
                & (ErpChartOfAccountModel.id == ErpJournalLineModel.account_id),
            )
            .where(
                ErpJournalLineModel.tenant_id == tenant_id,
                ErpJournalLineModel.entry_id.in_(entry_ids),
            )
            .order_by(ErpJournalLineModel.entry_id, ErpJournalLineModel.id)
        )
        lines_by_entry: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for row in line_rows.all():
            line = dict(row._mapping)
            lines_by_entry.setdefault(line.pop("entry_id"), []).append(line)
        for entry in entries:
            entry["lines"] = lines_by_entry.get(entry["id"], [])
            entry["amount"] = sum(
                (line["debit"] or 0) - (line["credit"] or 0) for line in entry["lines"]
            )
        # json round-trip ensures UUID/datetime/Decimal are stringified for JSONB storage
        return cast("list[dict[str, Any]]", json.loads(json.dumps(entries, default=str)))

    # ------------------------------------------------------------------ A6
    async def next_doc_version(
        self, tenant_id: uuid.UUID, doc_type: str, snapshot_id: uuid.UUID
    ) -> int:
        """Next version number for a (doc_type, snapshot) artifact family."""
        latest = await self._db.execute(
            select(func.max(ErpAiDocModel.version)).where(
                ErpAiDocModel.tenant_id == tenant_id,
                ErpAiDocModel.doc_type == doc_type,
                ErpAiDocModel.snapshot_id == snapshot_id,
            )
        )
        current = latest.scalar_one()
        return int(current or 0) + 1

    async def create_doc(
        self,
        *,
        tenant_id: uuid.UUID,
        doc_type: str,
        snapshot_id: uuid.UUID,
        snapshot_data: dict[str, Any],
        version: int,
        pdf_bytes: bytes | None,
        watermarked: bool,
    ) -> ErpAiDocModel:
        model = ErpAiDocModel(
            tenant_id=tenant_id,
            doc_type=doc_type,
            snapshot_id=snapshot_id,
            snapshot_data=snapshot_data,
            version=version,
            status="draft",
            watermarked=watermarked,
            pdf_bytes=pdf_bytes,
        )
        self._db.add(model)
        await self._db.flush()
        await self._db.refresh(model)
        return model

    async def get_doc(self, tenant_id: uuid.UUID, doc_id: uuid.UUID) -> ErpAiDocModel | None:
        result = await self._db.execute(
            select(ErpAiDocModel).where(
                ErpAiDocModel.tenant_id == tenant_id, ErpAiDocModel.id == doc_id
            )
        )
        return result.scalar_one_or_none()

    async def list_docs(
        self,
        tenant_id: uuid.UUID,
        doc_type: str | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[ErpAiDocModel]:
        stmt = select(ErpAiDocModel).where(ErpAiDocModel.tenant_id == tenant_id)
        if doc_type:
            stmt = stmt.where(ErpAiDocModel.doc_type == doc_type)
        stmt = stmt.order_by(ErpAiDocModel.created_at.desc()).limit(limit).offset(offset)
        result = await self._db.execute(stmt)
        return result.scalars().all()

    async def approve_doc(
        self, tenant_id: uuid.UUID, doc_id: uuid.UUID, user_id: uuid.UUID
    ) -> ErpAiDocModel | None:
        model = await self.get_doc(tenant_id, doc_id)
        if model is None:
            return None
        model.status = "approved"
        model.watermarked = False
        model.approved_by_user_id = user_id
        model.approved_at = datetime.now()
        await self._db.flush()
        await self._db.refresh(model)
        return model

    # ------------------------------------------------------------------ A5
    async def create_tax_summary(
        self,
        *,
        tenant_id: uuid.UUID,
        period_id: uuid.UUID,
        period_name: str,
        start_date: date,
        end_date: date,
        snapshot_id: uuid.UUID | None,
        snapshot: dict[str, Any],
        categories: list[dict[str, Any]],
        total_input: Decimal,
        total_output: Decimal,
        model_used: str,
    ) -> ErpTaxSummaryModel:
        model = ErpTaxSummaryModel(
            tenant_id=tenant_id,
            period_id=period_id,
            period_name=period_name,
            start_date=start_date,
            end_date=end_date,
            snapshot_id=snapshot_id,
            snapshot=snapshot,
            categories=categories,
            total_input=total_input,
            total_output=total_output,
            status="draft",
            model_used=model_used,
        )
        self._db.add(model)
        await self._db.flush()
        await self._db.refresh(model)
        return model

    async def get_tax_summary(
        self, tenant_id: uuid.UUID, summary_id: uuid.UUID
    ) -> ErpTaxSummaryModel | None:
        result = await self._db.execute(
            select(ErpTaxSummaryModel).where(
                ErpTaxSummaryModel.tenant_id == tenant_id, ErpTaxSummaryModel.id == summary_id
            )
        )
        return result.scalar_one_or_none()

    async def list_tax_summaries(
        self,
        tenant_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[ErpTaxSummaryModel]:
        stmt = (
            select(ErpTaxSummaryModel)
            .where(ErpTaxSummaryModel.tenant_id == tenant_id)
            .order_by(ErpTaxSummaryModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._db.execute(stmt)
        return result.scalars().all()

    async def set_tax_summary_status(
        self, tenant_id: uuid.UUID, summary_id: uuid.UUID, status: str, user_id: uuid.UUID
    ) -> ErpTaxSummaryModel | None:
        model = await self.get_tax_summary(tenant_id, summary_id)
        if model is None:
            return None
        model.status = status
        model.approved_by_user_id = user_id
        model.approved_at = datetime.now()
        await self._db.flush()
        await self._db.refresh(model)
        return model
