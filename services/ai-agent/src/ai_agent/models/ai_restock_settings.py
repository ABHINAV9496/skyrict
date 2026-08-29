"""ai_restock_settings - per-tenant tunables for the AI restock features
(INV-AI-002).

Controls the v2 restock formula inputs (``lead_time_days``, ``safety_factor``)
and the ``v2_enabled`` feature flag that gates the enhanced formula per tenant.
Also carries the anomaly false-positive suppression ``fp_threshold``, detection
``sensitivity``, and the CRITICAL-anomaly ``email_alerts_enabled`` toggle so the
whole advisor surface is tunable without a redeploy.

Defaults are enforced at the database layer (server_default); the repo mirrors
them so a tenant without a row behaves identically to one that has the row.
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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiRestockSettingsModel(Base):
    """One row per tenant; never tenant-shared, RLS-scoped."""

    __tablename__ = "ai_restock_settings"
    __table_args__ = (
        CheckConstraint("lead_time_days > 0", name="ck_ai_restock_settings_lead_time_positive"),
        CheckConstraint("safety_factor > 0", name="ck_ai_restock_settings_safety_factor_positive"),
        CheckConstraint(
            "sensitivity >= 0 AND sensitivity <= 1",
            name="ck_ai_restock_settings_sensitivity_range",
        ),
        CheckConstraint(
            "fp_threshold >= 0 AND fp_threshold <= 1",
            name="ck_ai_restock_settings_fp_threshold_range",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    lead_time_days: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, server_default=text("7")
    )
    safety_factor: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, server_default=text("1")
    )
    v2_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    sensitivity: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, server_default=text("0.5")
    )
    fp_threshold: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, server_default=text("0.5")
    )
    email_alerts_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
