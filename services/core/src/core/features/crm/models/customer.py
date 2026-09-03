"""erp_crm_customers - accounts we do business with, tenant-scoped with RLS.

Tenant-scoped, composite primary key ``(tenant_id, id)``, soft-deleted via
``is_active`` (the ERP convention - there is NO customer status enum; locked
SKY-43 decision). ``customer_code`` is unique per tenant and is the stable
external key the API accepts. A NULL ``credit_limit`` means "no limit" (the
confirm-time credit check passes); ``currency_code`` is only meaningful
alongside a limit (DB CHECK).
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
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpCrmCustomerModel(Base):
    __tablename__ = "erp_crm_customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_code", name="uq_erp_crm_customers_tenant_code"),
        CheckConstraint(
            "credit_limit IS NULL OR credit_limit >= 0",
            name="ck_erp_crm_customers_credit_limit_non_negative",
        ),
        CheckConstraint(
            "credit_limit IS NULL OR currency_code IS NOT NULL",
            name="ck_erp_crm_customers_currency_present",
        ),
        Index("ix_erp_crm_customers_tenant_name", "tenant_id", "name"),
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
    customer_code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # source_opportunity_id: soft link to the won opportunity this customer was
    # promoted from (plain UUID, NO FK - migration 0015, UNIQUE
    # (tenant_id, source_opportunity_id)).
    source_opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency_code: Mapped[str | None] = mapped_column(
        String(3),
        ForeignKey("erp_currencies.code"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
