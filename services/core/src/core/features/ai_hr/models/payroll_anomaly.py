"""ai_payroll_anomaly_log — payroll anomaly findings.

Written by the anomaly detection rules (Commit 4); read for the anomaly feed
and dispositions. ``severity`` is ``low|medium|high|critical`` (spec §7.1);
``status`` follows the lifecycle ``open -> acknowledged|dismissed|resolved``.
``run_id`` always references a payroll run; ``employee_id`` is nullable because
``duplicate_account`` findings span multiple entries.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class AnomalyType:
    """Valid values for ``anomaly_type``."""

    NET_PAY_DELTA = "net_pay_delta"
    DUPLICATE_ACCOUNT = "duplicate_account"
    GHOST_EMPLOYEE = "ghost_employee"


class AnomalySeverity:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AnomalyStatus:
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"


class PayrollAnomalyModel(Base):
    """One detected anomaly row."""

    __tablename__ = "ai_payroll_anomaly_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["erp_payroll_runs.tenant_id", "erp_payroll_runs.id"],
            name="fk_ai_payroll_anomaly_log_run",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_ai_payroll_anomaly_log_employee",
        ),
        CheckConstraint(
            "anomaly_type IN ('net_pay_delta', 'duplicate_account', 'ghost_employee')",
            name="ck_ai_payroll_anomaly_log_type",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_ai_payroll_anomaly_log_severity",
        ),
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'dismissed', 'resolved')",
            name="ck_ai_payroll_anomaly_log_status",
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
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    anomaly_type: Mapped[str] = mapped_column(String(24), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(14), nullable=False, server_default="open")
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
