"""AI document artifacts - versioned, DRAFT-gated PDF packs (FIN-AI-004 A6).

One row per rendered artifact (P&L, balance sheet) built from a report
snapshot. ``status`` moves draft -> approved|rejected; a draft artifact keeps
``watermarked=true`` and its PDF bytes carry the diagonal DRAFT overlay.
Approval records the acting user and time (audit-logged separately by the
service).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    LargeBinary,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpAiDocModel(Base):
    __tablename__ = "erp_ai_documents"
    __table_args__ = (
        CheckConstraint(
            "doc_type IN ('pnl', 'balance_sheet', 'tax_summary', 'audit_narrative')",
            name="ck_erp_ai_documents_doc_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'approved', 'rejected')",
            name="ck_erp_ai_documents_status",
        ),
        CheckConstraint("version >= 1", name="ck_erp_ai_documents_version"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'pnl'"))
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    snapshot_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    watermarked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pdf_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
