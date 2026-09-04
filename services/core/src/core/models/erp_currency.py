"""ERP currency reference model - global (not tenant-scoped), seeded ISO 4217."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpCurrencyModel(Base):
    """A supported ISO 4217 currency code.

    Global reference data: readable by every tenant, never RLS-scoped. Seeded
    by migration 0001; future money-bearing tables FK to ``code``.
    """

    __tablename__ = "erp_currencies"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(8), nullable=False, server_default="")
    numeric: Mapped[str] = mapped_column(String(3), nullable=False, server_default="")
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
