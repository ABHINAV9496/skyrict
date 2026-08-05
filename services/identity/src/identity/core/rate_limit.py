from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog
from redis.asyncio import Redis

from identity.core.config import settings
from skyrict_common.exceptions import RateLimitExceededError, RateLimitUnavailableError

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

logger = structlog.get_logger("identity.rate_limit")


class RateLimiter:
    def __init__(self, *, redis_client: AsyncRedis | None = None) -> None:
        self._client: AsyncRedis | None = redis_client
        self._owns_client = redis_client is None

    async def _get_client(self) -> AsyncRedis | None:
        if self._client is None and self._owns_client:
            self._client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._client

    async def is_allowed(self, *, key: str, limit: int, window_seconds: int) -> bool:
        client = await self._get_client()
        if client is None:
            return True
        try:
            window = int(time.time()) // max(window_seconds, 1)
            rl_key = f"rl:{key}:{window}"
            count = int(await client.incr(rl_key))
            if count == 1:
                await client.expire(rl_key, window_seconds + 1)
            return count <= limit
        except Exception as exc:
            if settings.RATE_LIMIT_FAIL_CLOSED:
                logger.warning("rate_limit_fail_closed", key=key, error=str(exc))
                raise RateLimitUnavailableError() from exc
            logger.warning("rate_limit_fail_open", key=key, error=str(exc))
            return True

    async def enforce(self, *, key: str, limit: int, window_seconds: int) -> None:
        if not await self.is_allowed(key=key, limit=limit, window_seconds=window_seconds):
            raise RateLimitExceededError("Too many attempts. Try again later.")


limiter = RateLimiter()
