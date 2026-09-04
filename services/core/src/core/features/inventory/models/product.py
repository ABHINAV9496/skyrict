"""Tenant-scoped ERP product ORM model - RLS-protected, composite primary key.

Follows the 0001 composite-FK convention: ``tenant_id`` is both the RLS column
and a member of the primary key, so ``(tenant_id, id)`` can be referenced by
child tables with a composite FK that keeps referential integrity aligned with
RLS. Prices are stored as ``Numeric(18,4)`` + an ISO 4217 currency code FK -
never floats.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpProductModel(Base):
    __tablename__ = "erp_products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_erp_products_tenant_sku"),
        CheckConstraint("cost_price >= 0", name="ck_erp_products_cost_price_non_negative"),
        CheckConstraint("sell_price >= 0", name="ck_erp_products_sell_price_non_negative"),
        CheckConstraint("reorder_point >= 0", name="ck_erp_products_reorder_point_non_negative"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cost_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    cost_currency_code: Mapped[str] = mapped_column(
        String(3),
        ForeignKey("erp_currencies.code"),
        nullable=False,
        server_default=text("'USD'"),
    )
    sell_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    sell_currency_code: Mapped[str] = mapped_column(
        String(3),
        ForeignKey("erp_currencies.code"),
        nullable=False,
        server_default=text("'USD'"),
    )
    reorder_point: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
