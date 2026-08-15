"""erp_crm_opportunities — pipeline deals, tenant-scoped with RLS.

Tenant-scoped, composite primary key ``(tenant_id, id)``. The pipeline moves
``prospecting -> qualified -> proposal -> negotiation`` and terminates at
``won`` or ``lost``. The DB CHECK ``ck_erp_crm_opportunities_stage_outcome``
ties each terminal stage to its timestamp (``won_at`` iff ``stage = 'won'``,
``lost_at`` iff ``stage = 'lost'``) and forbids both.

Deliberately customer-less in Phase 1: a won opportunity is promoted to a
customer by the service layer, so there is no ``customer_id`` FK here (locked
SKY-43 decision). ``amount`` is nullable (early-stage deals have no value yet)
and ``currency_code`` is only meaningful alongside it (DB CHECK).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.domain.value_objects import OpportunityStage
from core.models.base import Base


class ErpCrmOpportunityModel(Base):
    __tablename__ = "erp_crm_opportunities"
    __table_args__ = (
        CheckConstraint(
            "amount IS NULL OR amount >= 0",
            name="ck_erp_crm_opportunities_amount_non_negative",
        ),
        CheckConstraint(
            "amount IS NULL OR currency_code IS NOT NULL",
            name="ck_erp_crm_opportunities_currency_present",
        ),
        CheckConstraint(
            "probability >= 0 AND probability <= 100",
            name="ck_erp_crm_opportunities_probability_range",
        ),
        CheckConstraint(
            "((stage = 'won') = (won_at IS NOT NULL))"
            " AND ((stage = 'lost') = (lost_at IS NOT NULL))"
            " AND (NOT (won_at IS NOT NULL AND lost_at IS NOT NULL))",
            name="ck_erp_crm_opportunities_stage_outcome",
        ),
        Index("ix_erp_crm_opportunities_tenant_stage", "tenant_id", "stage"),
        Index("ix_erp_crm_opportunities_tenant_owner", "tenant_id", "owner_id"),
        Index("ix_erp_crm_opportunities_tenant_team", "tenant_id", "team_id"),
        Index("ix_erp_crm_opportunities_tenant_close", "tenant_id", "expected_close_date"),
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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[OpportunityStage] = mapped_column(
        Enum(
            OpportunityStage,
            name="erp_crm_opportunity_stage",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        server_default=text("'prospecting'"),
    )
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency_code: Mapped[str | None] = mapped_column(
        String(3),
        ForeignKey("erp_currencies.code"),
        nullable=True,
    )
    probability: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    expected_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    won_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lost_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lost_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
