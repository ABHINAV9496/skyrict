"""Application lifespan - startup verification and graceful shutdown.

Extracted from main.py for testability and separation of concerns.

Startup: verifies every required dependency ONCE (database, Redis, JWT keys)
and refuses to boot on failure - the orchestrator sees the non-zero exit and
restarts the pod instead of serving traffic with a dead dependency. The
readiness gate only opens after verification succeeds; ``GET /ready`` reports
it (with lightweight live probes) but never re-runs this verification.

Shutdown: closes the gate so probes drain the pod, disposes the DB engine,
and closes the Redis pool.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from identity.api import readiness
from identity.core.config import settings
from identity.core.logging import configure_identity_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan - startup and graceful shutdown."""
    configure_identity_logging(log_level=settings.LOG_LEVEL, json_output=settings.LOG_JSON)

    logger = get_logger("identity.startup")
    logger.info(
        "service.starting",
        environment=settings.ENVIRONMENT.value,
        debug=settings.DEBUG,
        log_level=settings.LOG_LEVEL,
    )

    # Startup verification - fail-fast: any failure raises StartupError and
    # the process exits immediately (orchestrator restarts the pod).
    await readiness.verify_startup_dependencies()
    readiness.mark_ready()
    logger.info("service.started", environment=settings.ENVIRONMENT.value)

    # Graceful shutdown: uvicorn owns SIGTERM/SIGINT handling; on signal it runs
    # this context manager's exit, closing the readiness gate and pools below.
    yield

    # Shutdown: close the readiness gate (probes start failing), then close
    # the DB engine and Redis pool so in-flight work can drain cleanly.
    readiness.mark_stopping()
    logger.info("service.stopping", environment=settings.ENVIRONMENT.value)

    from identity.core.redis import close_redis
    from identity.db.session import engine

    await engine.dispose()
    await close_redis()
