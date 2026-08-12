"""Tenant-scoped materialized stock level ORM model.

The row is a projection of the ``erp_stock_movements`` ledger, recomputed on
every write (see ``features/inventory/repository.py``). Its CHECK constraints
are the DB-level defense in depth: ``qty_on_hand >= 0`` (no negative stock) and
``0 <= qty_reserved <= qty_on_hand`` (no over-reservation) fail the whole
write transaction, including the ledger insert, independent of service logic.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Numeric,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpStockLevelModel(Base):
    __tablename__ = "erp_stock_levels"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "warehouse_id",
            name="uq_erp_stock_levels_product_warehouse",
        ),
        CheckConstraint("qty_on_hand >= 0", name="ck_erp_stock_levels_on_hand_non_negative"),
        CheckConstraint(
            "qty_reserved >= 0 AND qty_reserved <= qty_on_hand",
            name="ck_erp_stock_levels_reserved_range",
        ),
        # Composite-FK convention: a level can only reference a product and a
        # warehouse in the SAME tenant — referential integrity agrees with RLS.
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["erp_products.tenant_id", "erp_products.id"],
            ondelete="CASCADE",
            name="fk_erp_stock_levels_product_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["erp_warehouses.tenant_id", "erp_warehouses.id"],
            ondelete="CASCADE",
            name="fk_erp_stock_levels_warehouse_tenant",
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
    qty_on_hand: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    qty_reserved: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
