"""Redis hot cache for RAG semantic-search results.

Query normalization + hashing live here (feature layer): the SHA-256 hash of
the normalized text is the cache key per tenant. Hashing happens BEFORE any
embedding call, so identical queries skip embedding entirely.

Fail-open posture mirrors the rate limiter: a Redis blip must never take
semantic search down — ``get`` returns None (treated as a miss) and ``put``
logs + swallows, so retrieval still works while caching degrades gracefully.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Protocol

import structlog

if TYPE_CHECKING:
    import uuid

    from redis.asyncio import Redis

logger = structlog.get_logger("ai_agent.rag.cache")


def normalize_query(text: str) -> str:
    """Lowercase + collapse whitespace so cache hits survive trivial edits."""
    return " ".join(text.strip().lower().split())


def hash_query(text: str) -> str:
    """SHA-256 hex digest (64 chars, matches ai_query_cache.query_hash)."""
    return hashlib.sha256(normalize_query(text).encode("utf-8")).hexdigest()


def cache_key(tenant_id: uuid.UUID, query_hash: str, prefix: str = "ai:rag:cache:") -> str:
    """Redis key: never contains query text (PII) — hash + tenant only."""
    return f"{prefix}{tenant_id}:{query_hash}"


class QueryCache(Protocol):
    """Hot-path cache contract — implemented by RedisQueryCache."""

    async def get(self, *, tenant_id: uuid.UUID, query_hash: str) -> list[dict[str, object]] | None:
        """Return cached items or None on miss/infra error."""
        ...

    async def put(
        self,
        *,
        tenant_id: uuid.UUID,
        query_hash: str,
        payload: list[dict[str, object]],
        ttl_seconds: int,
    ) -> None:
        """Store items with the given TTL; never raises."""
        ...


class RedisQueryCache:
    """Redis-backed hot cache (lazy client, fail-open on errors).

    ``key_prefix`` scopes the keyspace per feature (RAG vs inventory search)
    so one Redis key scheme cannot leak between query caches.
    """

    def __init__(self, client: Redis | None = None, key_prefix: str = "ai:rag:cache:") -> None:
        self._client = client
        self._key_prefix = key_prefix

    def _get_client(self) -> Redis | None:
        if self._client is None:
            from ai_agent.core.redis import redis_client

            self._client = redis_client
        return self._client

    async def get(self, *, tenant_id: uuid.UUID, query_hash: str) -> list[dict[str, object]] | None:
        client = self._get_client()
        if client is None:
            return None
        try:
            raw = await client.get(cache_key(tenant_id, query_hash, self._key_prefix))
            if raw is None:
                return None
            decoded: Any = json.loads(raw)
            return decoded if isinstance(decoded, list) else None
        except Exception as exc:
            # Fail-open: a Redis blip degrades search to a full (uncached)
            # retrieval instead of taking the endpoint down.
            logger.warning("rag_cache_get_failed_open", error=str(exc))
            return None

    async def put(
        self,
        *,
        tenant_id: uuid.UUID,
        query_hash: str,
        payload: list[dict[str, object]],
        ttl_seconds: int,
    ) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            await client.set(
                cache_key(tenant_id, query_hash, self._key_prefix),
                json.dumps(payload),
                ex=ttl_seconds,
            )
        except Exception as exc:
            logger.warning("rag_cache_put_failed_open", error=str(exc))
