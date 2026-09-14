"""erp_journal_templates - recurring journal entry templates (FIN-AUT-003 B5).

Configuration, not ledger: lines are stored as a JSONB array of
``{account_code, debit, credit, currency}`` and resolved to account ids at
generate time. ``next_run_at`` is computed by the service from the 5-field
``cron_expression`` whenever the template is created or edited; the "run due"
endpoint scans ``enabled = true AND next_run_at <= now``. Generated DRAFT
entries are stamped ``source='journal_template'`` so the existing
``UNIQUE (tenant_id, source, source_ref)`` lock on journal entries makes every
occurrence exactly-once.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpJournalTemplateModel(Base):
    __tablename__ = "erp_journal_templates"
    __table_args__ = (
        Index("ix_erp_journal_templates_tenant_due", "tenant_id", "enabled", "next_run_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cron_expression: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_date_offset_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lines: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
