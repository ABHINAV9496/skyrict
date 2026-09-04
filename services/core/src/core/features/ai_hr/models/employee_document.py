"""erp_employee_documents - the compliance source table.

Holds an employee's documents / certifications per ``erp_document_type``.
``expiry_date`` enables the ``document_expiry`` and ``training_overdue``
compliance rules; ``is_required`` marks a document as a hard requirement. The
``doc_type`` column uses the shared ``erp_document_type`` enum.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class DocumentType(enum.StrEnum):
    """Native enum ``erp_document_type`` (created by migration 0020)."""

    WORK_PERMIT = "work_permit"
    VISA = "visa"
    NATIONAL_ID = "national_id"
    PASSPORT = "passport"
    CONTRACT = "contract"
    CERTIFICATION = "certification"
    MEDICAL = "medical"
    OTHER = "other"


class EmployeeDocumentModel(Base):
    """A document/certification attached to an employee within a tenant."""

    __tablename__ = "erp_employee_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_employee_documents_employee",
        ),
        CheckConstraint(
            "status IN ('active', 'expired', 'archived')",
            name="ck_erp_employee_documents_status",
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
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    doc_type: Mapped[DocumentType] = mapped_column(
        Enum(
            DocumentType,
            name="erp_document_type",
            create_type=False,
            values_callable=lambda cls: [m.value for m in cls],
        ),
        nullable=False,
    )
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
