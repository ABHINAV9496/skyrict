"""erp_sales_order_lines - line items of a sales order, tenant-scoped with RLS.

Tenant-scoped, composite primary key ``(tenant_id, id)``. Two composite FKs
keep referential integrity aligned with RLS: the line can only reference its
order and its product in the SAME tenant. ``product_id`` is a REAL hard FK to
inventory's ``erp_products`` (RESTRICT - locked SKY-43 decision), so a line
can never point at a cross-tenant or non-existent product at the constraint
level.

``product_name`` / ``sku`` are denormalized snapshots taken at order time so
order history stays stable even if the product catalog later changes.
``line_total`` is a cached projection (service recomputes it in CRM-BE-002).
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


class ErpSalesOrderLineModel(Base):
    __tablename__ = "erp_sales_order_lines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["erp_sales_orders.tenant_id", "erp_sales_orders.id"],
            ondelete="CASCADE",
            name="fk_erp_sales_order_lines_order_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["erp_products.tenant_id", "erp_products.id"],
            ondelete="RESTRICT",
            name="fk_erp_sales_order_lines_product_tenant",
        ),
        CheckConstraint("quantity > 0", name="ck_erp_sales_order_lines_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_erp_sales_order_lines_unit_price_non_negative"),
        CheckConstraint("discount >= 0", name="ck_erp_sales_order_lines_discount_non_negative"),
        CheckConstraint("tax >= 0", name="ck_erp_sales_order_lines_tax_non_negative"),
        CheckConstraint("line_total >= 0", name="ck_erp_sales_order_lines_total_non_negative"),
        Index("ix_erp_sales_order_lines_tenant_order", "tenant_id", "order_id"),
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
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    discount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    tax: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
