"""ai_compliance_checks - compliance findings for the v1 rule pack.

Written by the compliance engine (Commit 4); read for the compliance feed and
dispositions. ``owner_rule`` names the routing owner key (``hr_admin``,
``compliance_officer``); ``owner_user_id`` is set when a finding is assigned.
``employee_id`` is nullable for tenant-level findings.
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


class ComplianceCheckType:
    """Valid values for ``check_type``."""

    DOCUMENT_EXPIRY = "document_expiry"
    TRAINING_OVERDUE = "training_overdue"
    CONTRACT_MISSING_FIELD = "contract_missing_field"


class ComplianceStatus:
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class ComplianceCheckModel(Base):
    """One compliance finding."""

    __tablename__ = "ai_compliance_checks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_ai_compliance_checks_employee",
        ),
        CheckConstraint(
            "check_type IN ('document_expiry', 'training_overdue', 'contract_missing_field')",
            name="ck_ai_compliance_checks_type",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_ai_compliance_checks_severity",
        ),
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')",
            name="ck_ai_compliance_checks_status",
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
    employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    check_type: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    owner_rule: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(14), nullable=False, server_default="open")
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
