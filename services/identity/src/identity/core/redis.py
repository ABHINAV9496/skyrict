"""Async Redis client - the ONE place Redis connections are created.

Mirrors db/session.py: a module-level client built from settings so the whole
service shares a single connection pool. Redis clients are lazy - no TCP
connection is opened until the first command - so importing this module (and
even constructing the app) never blocks on Redis.

The pool is closed during graceful shutdown via :func:`close_redis`.
"""

from __future__ import annotations

from redis.asyncio import Redis

from identity.core.config import settings

redis_client: Redis = Redis.from_url(settings.REDIS_URL)


async def close_redis() -> None:
    """Close the shared Redis connection pool (used during graceful shutdown)."""
    await redis_client.aclose()
