"""erp_expense_policy_violations - persisted policy breaches (SKY-85 B16).

Written on every evaluation that does not pass clean so reporting can group by
``reason_code`` later. A ``blocked`` violation refuses the claim outright (the
claim row is never created); a ``warning`` violation persists the reason code
but the claim proceeds for human review (its ``claim_id`` links back).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpExpensePolicyViolationModel(Base):
    __tablename__ = "erp_expense_policy_violations"
    __table_args__ = (
        Index("ix_erp_expense_policy_violations_tenant_code", "tenant_id", "reason_code"),
        Index(
            "ix_erp_expense_policy_violations_tenant_claim",
            "tenant_id",
            "claim_id",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
