"""erp_expense_policies - per-category expense rules (FIN-AUT-004, SKY-85 B16).

One row per category (the service resolves claims to a policy by category;
claims in a category with no policy row fall back to the ``DEFAULT`` row a
tenant can create, or no cap/receipt gate when absent). ``cap_amount`` is the
per-claim ceiling; ``requires_receipt`` gates claims with no receipt URL;
``advance_limit`` bounds the advance attached to a claim.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpExpensePolicyModel(Base):
    __tablename__ = "erp_expense_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "category", name="uq_erp_expense_policies_tenant_category"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cap_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    requires_receipt: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    advance_limit: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
