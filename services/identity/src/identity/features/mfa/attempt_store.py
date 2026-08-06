"""Redis-backed failed-attempt tracking for MFA enrollment.

Guards the enrollment-confirm endpoint (``POST /mfa/verify``) against
brute-forcing the TOTP code during the forced-enrollment window. The login
challenge path is already protected by the single-use ``MfaChallengeStore``,
but enrollment has no challenge token, so this store keys on the user id
instead. The counter is cleared on a successful verification and expires on
its own otherwise, bounding the lockout to ``MFA_ENROLL_LOCKOUT_SECONDS``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from identity.core.redis import redis_client

if TYPE_CHECKING:
    from redis.asyncio import Redis


def _attempts_key(user_id: str) -> str:
    return f"mfa_enroll_attempts:{user_id}"


def _as_int(value: object) -> int:
    try:
        if isinstance(value, bytes):
            return int(value.decode("utf-8"))
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


class MFAAttemptStore:
    """Redis-backed counter of failed enrollment verifications per user."""

    def __init__(self, client: Redis | None = None) -> None:
        self._client = client if client is not None else redis_client

    async def get_attempts(self, user_id: str) -> int:
        """Return the current failed-attempt count for a user."""
        return _as_int(await self._client.get(_attempts_key(user_id)))

    async def increment_attempts(self, user_id: str, *, ttl_seconds: int) -> int:
        """Record one more attempt and return the new count.

        The key's TTL is set on the first attempt so the count (and therefore
        the lockout) expires after ``ttl_seconds``.
        """
        key = _attempts_key(user_id)
        count = _as_int(await self._client.incr(key))
        ttl = _as_int(await self._client.ttl(key))
        if ttl < 0:
            await self._client.expire(key, ttl_seconds)
        return count

    async def clear(self, user_id: str) -> None:
        """Reset the failed-attempt count after a successful verification."""
        await self._client.delete(_attempts_key(user_id))
