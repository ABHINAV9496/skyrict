"""/ai/inventory/search response schemas (SKY-70).

Field contracts visible to the core proxy and the web app:

- ``source`` is ``exact`` (ILIKE substring hit) or ``semantic`` (vector hit).
  Exact hits always rank above semantic and carry ``matched_fields`` (which
  catalog fields matched); semantic hits carry ``score`` (1 - cosine distance)
  instead - a concatenated embedding cannot be attributed to one field.
- ``cost_price`` is a string money amount attached only when the core proxy
  forwarded ``X-AI-Valuation-Disclosed: 1`` (caller holds
  ``erp.inventory.valuation``); otherwise None.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InventorySearchItem(BaseModel):
    """One product hit with provenance and (optional) valuation fields."""

    model_config = ConfigDict(from_attributes=True)

    item_id: uuid.UUID
    sku: str
    name: str
    category: str | None = None
    unit: str | None = None
    source: Literal["exact", "semantic"]
    score: float = Field(ge=0.0, le=1.0)
    matched_fields: list[str] | None = None
    cost_price: str | None = None


class InventorySearchResponse(BaseModel):
    """A single hybrid search execution (or cache hit)."""

    data: list[InventorySearchItem]
    cached: bool = False
    degraded: bool = False
    model_used: str | None = None
    latency_ms: int = 0
