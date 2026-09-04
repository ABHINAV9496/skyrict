"""erp_sales_orders - customer commitments, tenant-scoped with RLS.

Tenant-scoped, composite primary key ``(tenant_id, id)``, ``order_number``
unique per tenant. The status machine is ``draft -> confirmed -> fulfilled``
with ``cancelled`` terminal from draft/confirmed; the DB CHECK
``ck_erp_sales_orders_status_confirmed_at`` ties ``confirmed_at`` to
``confirmed``/``fulfilled``.

Money columns (``subtotal`` / ``discount`` / ``tax`` / ``total``) are a cached
projection recomputed from the lines by the service on every write (CRM-BE-002)
- never trusted from clients. ``credit_check`` records the confirm-time result
(``pending`` until confirm runs it). The composite FK to the customer keeps
referential integrity aligned with RLS: an order can only reference a customer
in the same tenant, RESTRICT because customers are soft-deleted.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.domain.value_objects import CreditCheckResult, OrderStatus
from core.models.base import Base


class ErpSalesOrderModel(Base):
    __tablename__ = "erp_sales_orders"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["erp_crm_customers.tenant_id", "erp_crm_customers.id"],
            ondelete="RESTRICT",
            name="fk_erp_sales_orders_customer_tenant",
        ),
        UniqueConstraint("tenant_id", "order_number", name="uq_erp_sales_orders_tenant_number"),
        CheckConstraint(
            "subtotal >= 0 AND discount >= 0 AND tax >= 0 AND total >= 0",
            name="ck_erp_sales_orders_amounts_non_negative",
        ),
        CheckConstraint(
            "(status IN ('confirmed', 'fulfilled')) = (confirmed_at IS NOT NULL)",
            name="ck_erp_sales_orders_status_confirmed_at",
        ),
        Index("ix_erp_sales_orders_tenant_status", "tenant_id", "status"),
        Index("ix_erp_sales_orders_tenant_customer", "tenant_id", "customer_id"),
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
    order_number: Mapped[str] = mapped_column(String(32), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(
            OrderStatus,
            name="erp_sales_order_status",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        server_default=text("'draft'"),
    )
    credit_check: Mapped[CreditCheckResult] = mapped_column(
        Enum(
            CreditCheckResult,
            name="erp_sales_credit_check_result",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        server_default=text("'pending'"),
    )
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    discount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    tax: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    currency_code: Mapped[str] = mapped_column(
        String(3),
        ForeignKey("erp_currencies.code"),
        nullable=False,
        server_default=text("'USD'"),
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
