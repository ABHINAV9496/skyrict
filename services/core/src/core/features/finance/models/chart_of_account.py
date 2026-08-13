"""erp_chart_of_accounts — the tenant's chart of accounts.

Accounts are never hard-deleted once referenced by journal/invoice history
(the composite FKs use RESTRICT); ``is_active`` is the only removal path.
``UNIQUE (tenant_id, code)`` keeps a tenant's codes unique (two tenants may
both use ``1100``) and feeds the ``account_code``-based journal entry API.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.domain.value_objects import AccountType
from core.models.base import Base


class ErpChartOfAccountModel(Base):
    __tablename__ = "erp_chart_of_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_erp_chart_of_accounts_tenant_code"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        Enum(
            AccountType,
            name="erp_account_type",
            create_type=False,
            values_callable=lambda cls: [member.value for member in cls],
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
