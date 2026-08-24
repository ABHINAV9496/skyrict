"""ai_anomalies - detected stock anomalies with the review workflow (spec §4.7).

Rows are created by the anomaly detector (scheduled scan over stock movements)
and transition ``open -> resolved | dismissed | escalated`` by a human.
``related_movement_ids`` keeps the evidence chain pointing at the core-owned
``erp_stock_movements`` ledger rows that triggered detection.

Cross-service UUID columns (``affected_product_id``, ``affected_warehouse_id``,
``reviewed_by``) carry NO FK: those tables are owned by core/identity in the
same shared database; integrity is validated through the core data-plane API
before a row is written (cross-service idiom, same as core_audit_logs'
``actor_user_id``).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiAnomalyModel(Base):
    """One detected stock anomaly awaiting (or past) human review."""

    __tablename__ = "ai_anomalies"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_ai_anomalies_severity",
        ),
        CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed', 'escalated')",
            name="ck_ai_anomalies_status",
        ),
        # Spec §4.7: triage queue per tenant - open items first, worst first.
        Index(
            "idx_ai_anomalies_tenant_status",
            "tenant_id",
            "status",
            "severity",
            text("created_at DESC"),
        ),
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
    anomaly_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    affected_product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    affected_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    related_movement_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'open'"))
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
