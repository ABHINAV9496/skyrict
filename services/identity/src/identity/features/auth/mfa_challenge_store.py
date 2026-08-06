"""Redis-backed storage for one-time MFA login challenges.

An mfaToken binds a login attempt to a user + tenant for a short TTL with a
bounded attempt budget. The challenge is consumed (deleted) on success or
when the attempt limit is hit, so each token is single-use.
"""

from __future__ import annotations

import json
import secrets
from typing import TYPE_CHECKING

from identity.core.config import settings
from identity.core.redis import redis_client

if TYPE_CHECKING:
    from redis.asyncio import Redis


def _challenge_key(token: str) -> str:
    return f"mfa_challenge:{token}"


def _attempts_key(token: str) -> str:
    return f"mfa_challenge_attempts:{token}"


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _as_int(value: object) -> int:
    try:
        return int(_as_str(value) or 0)
    except (TypeError, ValueError):
        return 0


def generate_mfa_token() -> str:
    """Return a cryptographically random mfaToken."""
    return secrets.token_urlsafe(32)


class MfaChallengeStore:
    """Redis-backed store for one-time MFA login challenges."""

    def __init__(self, client: Redis | None = None) -> None:
        self._client = client if client is not None else redis_client

    async def create(self, *, user_id: str, tenant_id: str) -> str:
        """Issue a new challenge and return its opaque mfaToken."""
        token = generate_mfa_token()
        payload = {"user_id": user_id, "tenant_id": tenant_id}
        await self._client.set(
            _challenge_key(token),
            json.dumps(payload),
            ex=settings.MFA_CHALLENGE_TTL_SECONDS,
        )
        await self._client.set(
            _attempts_key(token),
            "0",
            ex=settings.MFA_CHALLENGE_TTL_SECONDS,
        )
        return token

    async def get(self, token: str) -> dict[str, str] | None:
        """Return the challenge payload (user_id/tenant_id) or None if absent."""
        raw = _as_str(await self._client.get(_challenge_key(token)))
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("user_id"), str)
            or not isinstance(payload.get("tenant_id"), str)
        ):
            return None
        return {"user_id": payload["user_id"], "tenant_id": payload["tenant_id"]}

    async def get_attempts(self, token: str) -> int:
        """Return the number of failed attempts recorded for this token."""
        return _as_int(await self._client.get(_attempts_key(token)))

    async def increment_attempts(self, token: str) -> int:
        """Record one more attempt and return the new count."""
        key = _attempts_key(token)
        count = _as_int(await self._client.incr(key))
        ttl = _as_int(await self._client.ttl(key))
        if ttl < 0:
            await self._client.expire(key, settings.MFA_CHALLENGE_TTL_SECONDS)
        return count

    async def consume(self, token: str) -> None:
        """Delete the challenge and its attempt counter (single-use)."""
        await self._client.delete(_challenge_key(token), _attempts_key(token))
