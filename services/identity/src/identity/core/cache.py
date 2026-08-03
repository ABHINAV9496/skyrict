"""Async TTL cache — small in-memory store with per-key expiry.

Foundational plumbing for per-tenant caches (JWKS keys, permission lookups).
The interface (``set``/``get``/``delete``/``get_or_set``) mirrors what a
Redis-backed cache should expose so a distributed implementation can drop in
without touching call sites.

Not safe for multi-process consistency — use for short-lived, per-process
derived data only. For shared state across replicas, introduce a Redis-backed
cache with the same interface instead.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    """In-memory cache keyed by string with per-key absolute expiry."""

    def __init__(self, *, default_ttl_seconds: float = 300.0) -> None:
        self._default_ttl_seconds = default_ttl_seconds
        self._store: dict[str, tuple[float, T]] = {}

    def set(self, key: str, value: T, *, ttl_seconds: float | None = None) -> None:
        """Store ``value`` at ``key``, expiring after the TTL (default if unset)."""
        ttl = self._default_ttl_seconds if ttl_seconds is None else ttl_seconds
        self._store[key] = (time.monotonic() + ttl, value)

    def get(self, key: str) -> T | None:
        """Return the cached value, or None when missing/expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def delete(self, key: str) -> None:
        """Remove ``key`` from the cache."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Drop every cached entry."""
        self._store.clear()

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[T]],
        *,
        ttl_seconds: float | None = None,
    ) -> T:
        """Return the cached value or populate it via ``factory``.

        Concurrent callers may both compute the value (no locking) — safe for
        idempotent factories such as loading an RSA public key.
        """
        cached = self.get(key)
        if cached is not None:
            return cached
        value = await factory()
        self.set(key, value, ttl_seconds=ttl_seconds)
        return value
