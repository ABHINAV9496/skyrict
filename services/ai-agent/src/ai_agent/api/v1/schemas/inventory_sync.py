"""/ai/inventory/embeddings/sync request/response schemas (SKY-70).

Payload contract between core's post-commit product-change dispatch and the
AI agent's snapshot writer. Core sends exactly the fields the snapshot embeds
(sku, name, category, unit) - never money or PII (spec §5.5). ``removes``
never need vectors, so they apply even when no embedding provider is
configured (``skipped=true`` marks upserts that could not be embedded).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class ProductUpsert(BaseModel):
    """One product to (re)embed in this tenant's snapshot."""

    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=10000)
    category: str | None = Field(default=None, max_length=100)
    unit: str | None = Field(default=None, max_length=32)


class ProductRemove(BaseModel):
    """One product to drop from this tenant's snapshot."""

    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID


class InventorySyncRequest(BaseModel):
    """One batch of product changes from core's dispatch loop."""

    model_config = ConfigDict(extra="forbid")

    upserts: list[ProductUpsert] = Field(default_factory=list, max_length=500)
    removes: list[ProductRemove] = Field(default_factory=list, max_length=500)


class InventorySyncResponse(BaseModel):
    """Result of applying one sync batch."""

    upserts_applied: int = 0
    removes_applied: int = 0
    skipped: bool = False
    model_used: str | None = None
    dims: int | None = None
