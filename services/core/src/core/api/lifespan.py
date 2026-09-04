"""Application lifespan - startup verification and graceful shutdown.

Extracted from main.py for testability and separation of concerns.

Startup: configures structured logging and verifies every required dependency
ONCE (database, JWT public key) and refuses to boot on failure - the
orchestrator sees the non-zero exit and restarts the pod instead of serving
traffic with a dead dependency. The readiness gate only opens after
verification succeeds; ``GET /ready`` reports it (with lightweight live
probes) but never re-runs this verification.

Shutdown: closes the gate so probes drain the pod, then disposes the DB
engine.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from core.api import readiness
from core.core.config import settings
from core.core.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan - startup and graceful shutdown."""
    configure_logging(log_level=settings.LOG_LEVEL, json_output=settings.LOG_JSON)

    logger = get_logger("core.startup")
    logger.info(
        "service.starting",
        environment=settings.ENVIRONMENT.value,
        debug=settings.DEBUG,
        log_level=settings.LOG_LEVEL,
    )

    # Outbound HTTP client for /api/v1/ai/* proxying to the ai-agent
    # microservice - one pooled client for the process lifetime.
    app.state.ai_client = httpx.AsyncClient(
        base_url=settings.AI_AGENT_URL,
        timeout=settings.AI_AGENT_TIMEOUT_SECONDS,
    )

    # Startup verification - fail-fast: any failure raises StartupError and
    # the process exits immediately (orchestrator restarts the pod).
    await readiness.verify_startup_dependencies()

    # Sync user→role grants from identity's tables into core's RBAC tables.
    # Bridges the gap where identity's seed creates user_roles rows but
    # core's seed only creates the role catalog - never the user→role grants
    # that require_permission resolves through.
    from core.seed import sync_rbac_from_identity

    try:
        await sync_rbac_from_identity()
    except Exception:
        logger.warning("rbac_sync.failed", exc_info=True)

    readiness.mark_ready()
    logger.info("service.started", environment=settings.ENVIRONMENT.value)

    # Graceful shutdown: uvicorn owns SIGTERM/SIGINT handling; on signal it
    # runs this context manager's exit, closing the readiness gate, the AI
    # client and the DB engine so in-flight work can drain cleanly.
    yield

    readiness.mark_stopping()
    logger.info("service.stopping", environment=settings.ENVIRONMENT.value)

    from core.db.session import engine

    await app.state.ai_client.aclose()
    await engine.dispose()
