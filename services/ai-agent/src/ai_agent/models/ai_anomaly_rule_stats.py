"""ai_anomaly_rule_stats - per-rule false-positive counters (INV-AI-002).

Feeds the sensitivity tuning loop: when a human dismisses an anomaly as a
false positive the counter increments, the rolling FP rate
``false_positives / findings_total`` is computed, and rules above the tenant's
``fp_threshold`` are suppressed on subsequent scans (spec §4.4 feedback loop).

One row per (tenant, anomaly_type); PK is the natural key.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiAnomalyRuleStatsModel(Base):
    __tablename__ = "ai_anomaly_rule_stats"
    __table_args__ = (
        CheckConstraint(
            "findings_total >= 0 AND false_positives >= 0",
            name="ck_ai_anomaly_rule_stats_counts_non_negative",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    anomaly_type: Mapped[str] = mapped_column(String(50), primary_key=True, nullable=False)
    findings_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    false_positives: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
