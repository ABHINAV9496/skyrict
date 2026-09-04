"""Request/response schemas for the RAG semantic-search endpoints (SKY-58)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RagSearchRequest(BaseModel):
    """POST /ai/rag/search body - one free-text query over the RAG store."""

    query: str = Field(min_length=1, max_length=500)


class RagSearchItem(BaseModel):
    """One retrieved parent chunk (score = best matching child)."""

    parent_id: uuid.UUID
    source_ref: str
    module: str
    chunk_text: str
    score: float
    child_hits: int
    metadata: dict[str, object] = Field(default_factory=dict)


class RagSearchResponse(BaseModel):
    """POST /ai/rag/search response.

    ``cached`` distinguishes a hot-cache hit (latency ~0, no embedding call)
    from a fresh retrieval, so operators can see cache effectiveness.
    """

    data: list[RagSearchItem]
    cached: bool
    model_used: str | None = None
    latency_ms: int


class RagModuleStatus(BaseModel):
    """Ingest counts for one module (documents/parents/chunks)."""

    module: str
    documents: int
    parents: int
    children: int
    last_ingested_at: datetime | None = None


class RagStatusResponse(BaseModel):
    """GET /ai/rag/status response - what the tenant's store contains."""

    modules: list[RagModuleStatus]
    total_parents: int
    total_children: int
