"""Redis-backed text-CAPTCHA store - issue, verify (single-use), attempt caps.

Follows the OTP store's keying and hashing conventions. The answer is stored
as a SHA-256 digest (never plaintext), keys auto-expire via ``SET ... EX``,
and a challenge is invalidated on success, expiry, or when its attempt budget
is exhausted. ``verify`` never reveals *why* a challenge was rejected, so an
attacker learns nothing beyond "not accepted".
"""

from __future__ import annotations

import hmac
import secrets
from typing import TYPE_CHECKING

from identity.core.config import settings
from identity.core.redis import redis_client
from identity.features.auth.captcha.captcha import hash_answer

if TYPE_CHECKING:
    from redis.asyncio import Redis


def _challenge_key(captcha_id: str) -> str:
    return f"signup_captcha:{captcha_id}"


def _attempts_key(captcha_id: str) -> str:
    return f"signup_captcha_attempts:{captcha_id}"


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _as_int(value: object) -> int:
    try:
        return int(_as_str(value) or 0)
    except (TypeError, ValueError):
        return 0


class CaptchaStore:
    """Issues challenges and verifies answers against the Redis digest."""

    def __init__(
        self,
        client: Redis | None = None,
        *,
        ttl_seconds: int | None = None,
        max_attempts: int | None = None,
    ) -> None:
        self._client = client if client is not None else redis_client
        self._ttl_seconds = ttl_seconds
        self._max_attempts = max_attempts

    def _ttl(self) -> int:
        return self._ttl_seconds or settings.CAPTCHA_TTL_SECONDS

    def _max_attempts_value(self) -> int:
        return self._max_attempts or settings.CAPTCHA_MAX_ATTEMPTS

    async def issue(self, answer: str) -> str:
        """Persist the answer's digest and return an opaque challenge id."""
        captcha_id = secrets.token_urlsafe(16)
        ttl = self._ttl()
        await self._client.set(_challenge_key(captcha_id), hash_answer(answer), ex=ttl)
        await self._client.set(_attempts_key(captcha_id), "0", ex=ttl)
        return captcha_id

    async def verify(self, captcha_id: str, answer: str) -> bool:
        """Return True only when the answer matches and the challenge was fresh.

        Each call consumes one attempt; a challenge is deleted after a correct
        answer, after its attempt budget is spent, or when it does not exist.
        """
        key = _challenge_key(captcha_id)
        stored = await self._client.get(key)
        if stored is None:
            return False
        if not await self._consume_attempt(captcha_id):
            await self._client.delete(key, _attempts_key(captcha_id))
            return False
        expected = _as_str(stored)
        if expected is None:
            return False
        if hmac.compare_digest(hash_answer(answer), expected):
            await self._client.delete(key, _attempts_key(captcha_id))
            return True
        return False

    async def _consume_attempt(self, captcha_id: str) -> bool:
        key = _attempts_key(captcha_id)
        count = _as_int(await self._client.incr(key))
        ttl = _as_int(await self._client.ttl(key))
        if ttl < 0:
            await self._client.expire(key, self._ttl())
        return count <= self._max_attempts_value()
