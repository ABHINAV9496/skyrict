"""Immutable tenant-scoped stock movement ORM model — the inventory ledger.

Every row is an insert-only fact: there is no ``updated_at`` column and the
repository exposes no update/delete path, so the ledger can never be silently
rewritten. ``(ref_type, ref_id, warehouse_id)`` is unique per tenant so an
idempotency probe can prove a source document line was applied to a warehouse
exactly once (a transfer pair shares one ref across two warehouses).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.domain.value_objects import StockMovementType
from core.models.base import Base


class ErpStockMovementModel(Base):
    __tablename__ = "erp_stock_movements"
    __table_args__ = (
        CheckConstraint("qty != 0", name="ck_erp_stock_movements_qty_nonzero"),
        UniqueConstraint(
            "tenant_id",
            "ref_type",
            "ref_id",
            "warehouse_id",
            name="uq_erp_stock_movements_ref",
        ),
        # Composite-FK convention: a movement can only reference a product and
        # a warehouse in the SAME tenant. RESTRICT (not CASCADE): the ledger is
        # eternal, and parents are soft-deleted (is_active = false) instead.
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["erp_products.tenant_id", "erp_products.id"],
            ondelete="RESTRICT",
            name="fk_erp_stock_movements_product_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["erp_warehouses.tenant_id", "erp_warehouses.id"],
            ondelete="RESTRICT",
            name="fk_erp_stock_movements_warehouse_tenant",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    movement_type: Mapped[StockMovementType] = mapped_column(
        Enum(
            StockMovementType,
            name="erp_stock_movement_type",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(32), nullable=False)
    ref_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
