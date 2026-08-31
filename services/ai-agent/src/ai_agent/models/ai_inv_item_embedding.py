"""ai_inv_item_embeddings - semantic product-search snapshot (SKY-70).

One row per ``(tenant_id, product_id)``: a 768-dimension pgvector embedding
of the product's existing catalog text (``"{sku} {name} {category} {unit}"``,
concatenated) plus the raw columns needed for exact-field fallback and
response payloads.

The table is a SNAPSHOT MIRROR of core-owned ``erp_products`` maintained by
outbox-style events (``inventory.product.upserted``/``.removed``) dispatched
via post-commit HTTP and by the ``inventory reindex`` CLI — never written by
any request path. Integrity is enforced by Postgres: the composite FK into
``erp_products`` (cross-service idiom, same as the SKY-68 restock tables) and
RLS via ``current_tenant_id()``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiInvItemEmbeddingModel(Base):
    __tablename__ = "ai_inv_item_embeddings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["erp_products.tenant_id", "erp_products.id"],
            ondelete="CASCADE",
            name="fk_ai_inv_item_embeddings_product_tenant",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    embedding = mapped_column(Vector(768), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dims: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("768"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
