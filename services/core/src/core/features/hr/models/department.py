"""erp_departments — organizational units.

``manager_employee_id`` is a self-referential composite FK to ``erp_employees``
(created in the migration via ALTER after that table exists — the two tables
reference each other). NO ACTION: a department whose rows are referenced can
never be hard-deleted, only soft-disabled via ``is_active``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class DepartmentModel(Base):
    """An organizational unit within a tenant."""

    __tablename__ = "erp_departments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_erp_departments_tenant_name"),
        ForeignKeyConstraint(
            ["tenant_id", "manager_employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_departments_manager_employee",
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
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    manager_employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
