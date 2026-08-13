"""erp_journal_entries — the header of one double-entry transaction.

``UNIQUE (tenant_id, source, source_ref)`` is the idempotency lock: an entry
stamped with the same provenance (e.g. source='invoice' + invoice id) can be
created only once, so a replayed request can never duplicate money. Manual
entries use ``source_ref = NULL``, which Postgres UNIQUE treats as distinct,
so unlimited manual entries are allowed. ``posted_by_user_id`` is a plain
UUID reference to identity users (no FK — identity owns users).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.domain.value_objects import EntryStatus
from core.models.base import Base


class ErpJournalEntryModel(Base):
    __tablename__ = "erp_journal_entries"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source", "source_ref", name="uq_erp_journal_entries_source_ref"
        ),
        Index("ix_erp_journal_entries_tenant_entry_date", "tenant_id", "entry_date"),
        Index("ix_erp_journal_entries_tenant_status", "tenant_id", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[EntryStatus] = mapped_column(
        Enum(
            EntryStatus,
            name="erp_entry_status",
            create_type=False,
            values_callable=lambda cls: [member.value for member in cls],
        ),
        nullable=False,
        server_default=text("'draft'"),
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
