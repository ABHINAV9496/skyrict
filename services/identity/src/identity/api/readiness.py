"""Application readiness gate and dependency probes.

Kept out of health.py (request handlers must never re-run the one-time
startup verification) and out of lifespan.py (so the probe logic is
unit-testable). The lifespan:

  1. runs :func:`verify_startup_dependencies` once — DB, Redis, and JWT keys
     — and raises :class:`StartupError` on any failure so the process
     refuses to boot (fail-fast);
  2. opens the gate with :func:`mark_ready` only after every check passed.

:func:`is_ready` gates ``GET /ready``: it returns 503 until startup
verification succeeded, then the handler runs the lightweight live probes
(:func:`check_database`, :func:`check_redis`) before reporting 200.
"""

from __future__ import annotations

import enum

from sqlalchemy import text

from identity.core.exceptions import StartupError
from identity.core.logging import get_logger
from identity.core.redis import redis_client
from identity.core.security import verify_jwt_keys_usable, verify_mfa_encryption_key
from identity.db.session import engine

logger = get_logger("identity.readiness")


class ReadinessState(enum.Enum):
    """Lifecycle state of the application gate."""

    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"


# Module-level gate. The lifespan (same event loop) is the only writer; the
# /ready handler is a reader, so plain module state is safe under asyncio.
_state: ReadinessState = ReadinessState.STARTING


def reset() -> None:
    """Reset the gate to STARTING — test fixtures only.

    The gate is module-global, so unit tests that exercise the closed-gate
    path must reset it to keep tests order-independent.
    """
    global _state
    _state = ReadinessState.STARTING


def mark_ready() -> None:
    """Open the gate after startup dependency verification succeeded."""
    global _state
    _state = ReadinessState.READY


def mark_stopping() -> None:
    """Close the gate during graceful shutdown so probes drain the pod."""
    global _state
    _state = ReadinessState.STOPPING


def is_ready() -> bool:
    """True only after startup verification succeeded and shutdown hasn't begun."""
    return _state is ReadinessState.READY


def get_state() -> ReadinessState:
    """Return the current gate state (observability and tests)."""
    return _state


async def check_database() -> None:
    """Probe Postgres with a trivial round-trip (SELECT 1).

    Raises on any failure — the caller decides whether that means a 503.
    """
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def check_redis() -> None:
    """Probe Redis with a PING round-trip.

    Raises on any failure — the caller decides whether that means a 503.
    """
    await redis_client.ping()


async def verify_startup_dependencies() -> None:
    """Verify every required dependency; raise :class:`StartupError` on failure.

    Runs exactly once, from the lifespan. Each check is logged with
    ``exc_info=True`` so the full failure is visible in logs even though the
    raised message stays generic (never embed connection strings or key
    material in exception text).
    """
    try:
        await check_database()
    except Exception:
        logger.error("startup.verification_failed", dependency="database", exc_info=True)
        raise StartupError("database verification failed at startup") from None

    try:
        await check_redis()
    except Exception:
        logger.error("startup.verification_failed", dependency="redis", exc_info=True)
        raise StartupError("redis verification failed at startup") from None

    try:
        verify_jwt_keys_usable()
    except StartupError:
        logger.error("startup.verification_failed", dependency="jwt_keys", exc_info=True)
        raise

    try:
        verify_mfa_encryption_key()
    except StartupError:
        logger.error("startup.verification_failed", dependency="mfa_encryption_key", exc_info=True)
        raise

    logger.info(
        "startup.dependencies_verified",
        checks={
            "database": "ok",
            "redis": "ok",
            "jwt_keys": "ok",
            "mfa_encryption_key": "ok",
        },
    )
