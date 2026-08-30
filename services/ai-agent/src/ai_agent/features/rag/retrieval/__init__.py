"""RAG retrieval — semantic search over the parent-child store (SKY-58).

Feature-layer code (no models/db imports — import-linter contract): the
service orchestrates an embedding provider, a retrieval store protocol, and a
Redis hot cache. Persistence of search results into ``ai_query_cache`` is
composed by the router from a repository (the composition root), keeping this
package pure feature orchestration.
"""

from ai_agent.features.rag.retrieval.cache import (
    RedisQueryCache,
    hash_query,
    normalize_query,
)
from ai_agent.features.rag.retrieval.service import RagRetrievalService, RetrievalItem

__all__ = [
    "RagRetrievalService",
    "RedisQueryCache",
    "RetrievalItem",
    "hash_query",
    "normalize_query",
]
