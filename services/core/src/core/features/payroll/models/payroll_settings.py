"""erp_payroll_settings - a single settings row per tenant.

Enforced by ``UNIQUE (tenant_id)``. Seeded once per tenant (default currency +
zero PF/tax rates); rates are later tuned per tenant by the payroll service.
Rates are stored as Numeric(18,4) (a percentage as a decimal fraction, e.g.
0.0500 = 5%), never a float.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.features.payroll.models.payroll_run import PayrollRounding
from core.models.base import Base


class PayrollSettingsModel(Base):
    """Tenant payroll configuration - exactly one row per tenant."""

    __tablename__ = "erp_payroll_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_erp_payroll_settings_tenant"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    pf_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    rounding: Mapped[PayrollRounding] = mapped_column(
        Enum(
            PayrollRounding,
            name="erp_payroll_rounding",
            create_type=False,
            values_callable=lambda cls: [m.value for m in cls],
        ),
        nullable=False,
        server_default=text("'nearest'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
