"""ai_crm_anomalies - one row per detected CRM pipeline anomaly (SKY-91).

The anomaly scan (deterministic rules over the tenant's CRM pipeline data)
persists one row per detected anomaly. ``opportunity_id`` is a plain UUID
with NO FK: the opportunity is owned by the core service in the shared
database (cross-service idiom, same as ``ai_deal_health.opportunity_id``).

Severity/status vocabulary is closed by CHECK constraints:

- ``severity`` is ``critical | warning`` (``info`` reserved for future
  informational rules).
- ``status`` is ``open`` when the scan detected it, ``resolved`` after a
  user acted on it, ``dismissed`` when a user deemed it a false positive.
  ``detected_at`` is always set; ``resolved_at``/``dismissed_at`` pin the
  terminal transition.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiCrmAnomalyModel(Base):
    """One deterministic anomaly detected on a CRM opportunity."""

    __tablename__ = "ai_crm_anomalies"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('critical', 'warning', 'info')", name="ck_ai_crm_anomalies_severity"
        ),
        CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')", name="ck_ai_crm_anomalies_status"
        ),
        Index(
            "idx_ai_crm_anomalies_tenant_opportunity",
            "tenant_id",
            "opportunity_id",
            "detected_at",
        ),
        Index("idx_ai_crm_anomalies_tenant_rule", "tenant_id", "rule_id", "detected_at"),
        Index("idx_ai_crm_anomalies_tenant_status", "tenant_id", "status", "detected_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    context: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
