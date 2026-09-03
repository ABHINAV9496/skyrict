"""erp_tenant_settings - generic tenant key-value configuration store.

Stores automation thresholds, toggles, and feature flags per tenant.
 ``(tenant_id, key)`` is unique; ``value`` is always TEXT (JSON booleans
 and numbers are stored as their string representations).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpTenantSettingModel(Base):
    __tablename__ = "erp_tenant_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_erp_tenant_settings_tenant_key"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(String(4096), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
