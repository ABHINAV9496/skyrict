"""ai_restock_demand_stats - rolling demand profile per product+warehouse
(INV-AI-002).

Backfilled from the core movement ledger by the restock scan: the aggregate
these rows hold (``avg_daily_demand``, ``demand_cv``, observed ``window_days``,
``last_receipt_at``) is what feeds the spec §3.2 enhanced restock formula. The
``eligible`` flag is the per-SKU gate: a SKU only enters the v2 formula once it
has enough observed history AND nonzero average demand.

Composite PK ``(tenant_id, product_id, warehouse_id)``; composite FKs into core
``erp_products`` / ``erp_warehouses`` (cross-service idiom - those tables are
owned by core in the same shared database).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiRestockDemandStatsModel(Base):
    __tablename__ = "ai_restock_demand_stats"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["erp_products.tenant_id", "erp_products.id"],
            ondelete="CASCADE",
            name="fk_ai_restock_demand_stats_product_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["erp_warehouses.tenant_id", "erp_warehouses.id"],
            ondelete="CASCADE",
            name="fk_ai_restock_demand_stats_warehouse_tenant",
        ),
        Index("idx_ai_restock_demand_stats_eligible", "tenant_id", "eligible"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    avg_daily_demand: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    demand_cv: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, server_default=text("0")
    )
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_receipt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
