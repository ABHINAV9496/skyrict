"""erp_journal_lines - the debit/credit legs of a journal entry.

This table carries the double-entry invariants as CHECK constraints: every
line is exactly one of debit/credit (never both, never neither) and never
zero. The composite FKs ``(tenant_id, entry_id)`` / ``(tenant_id, account_id)``
mean a line can only reference an entry and an account in the same tenant,
and RESTRICT keeps the ledger eternal (no deleting referenced history).
``currency`` / ``exchange_rate`` are reserved for multi-currency (v1: every
row uses the tenant default currency, rate 1).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpJournalLineModel(Base):
    __tablename__ = "erp_journal_lines"
    __table_args__ = (
        CheckConstraint(
            "(debit IS NOT NULL AND credit IS NULL) OR (debit IS NULL AND credit IS NOT NULL)",
            name="ck_erp_journal_lines_debit_xor_credit",
        ),
        CheckConstraint(
            "(debit IS NULL OR debit <> 0) AND (credit IS NULL OR credit <> 0)",
            name="ck_erp_journal_lines_amount_nonzero",
        ),
        CheckConstraint(
            "(debit IS NULL OR debit >= 0) AND (credit IS NULL OR credit >= 0)",
            name="ck_erp_journal_lines_amount_non_negative",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "entry_id"],
            ["erp_journal_entries.tenant_id", "erp_journal_entries.id"],
            ondelete="RESTRICT",
            name="fk_erp_journal_lines_entry",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["erp_chart_of_accounts.tenant_id", "erp_chart_of_accounts.id"],
            ondelete="RESTRICT",
            name="fk_erp_journal_lines_account",
        ),
        Index("ix_erp_journal_lines_tenant_entry", "tenant_id", "entry_id"),
        Index("ix_erp_journal_lines_tenant_account", "tenant_id", "account_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    debit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    credit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3),
        ForeignKey("erp_currencies.code"),
        nullable=False,
        server_default=text("'USD'"),
    )
    exchange_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
