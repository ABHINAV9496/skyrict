"""Application lifespan — startup verification and graceful shutdown.

Extracted from main.py for testability and separation of concerns.

Startup: configures structured logging and verifies every required dependency
ONCE (database, Redis, JWT public key) and refuses to boot on failure — the
orchestrator sees the non-zero exit and restarts the pod instead of serving
traffic with a dead dependency. The readiness gate only opens after
verification succeeds; ``GET /ready`` reports it (with lightweight live
probes) but never re-runs this verification.

AI providers are intentionally absent from this gate — see api/readiness.py.

Shutdown: closes the gate so probes drain the pod, then disposes the DB
engine and the Redis pool.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ai_agent.api import readiness
from ai_agent.core.config import settings
from ai_agent.core.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and graceful shutdown."""
    configure_logging(log_level=settings.LOG_LEVEL, json_output=settings.LOG_JSON)

    logger = get_logger("ai_agent.startup")
    logger.info(
        "service.starting",
        environment=settings.ENVIRONMENT.value,
        debug=settings.DEBUG,
        log_level=settings.LOG_LEVEL,
        inventory_service_url=settings.INVENTORY_SERVICE_URL,
    )

    # Startup verification — fail-fast: any failure raises StartupError and
    # the process exits immediately (orchestrator restarts the pod).
    await readiness.verify_startup_dependencies()
    readiness.mark_ready()
    logger.info("service.started", environment=settings.ENVIRONMENT.value)

    # Graceful shutdown: uvicorn owns SIGTERM/SIGINT handling; on signal it
    # runs this context manager's exit, closing the readiness gate and the
    # DB/Redis pools so in-flight work can drain cleanly.
    yield

    readiness.mark_stopping()
    logger.info("service.stopping", environment=settings.ENVIRONMENT.value)

    from ai_agent.core.redis import close_redis
    from ai_agent.db.session import engine

    await close_redis()
    await engine.dispose()
