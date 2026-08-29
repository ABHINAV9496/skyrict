"""Application lifespan — startup verification and graceful shutdown.

Extracted from main.py for testability and separation of concerns.

Startup: configures structured logging and verifies every required dependency
ONCE (database, JWT public key) and refuses to boot on failure — the
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
from core.core.config import Environment, settings
from core.core.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and graceful shutdown."""
    configure_logging(log_level=settings.LOG_LEVEL, json_output=settings.LOG_JSON)

    logger = get_logger("core.startup")
    logger.info(
        "service.starting",
        environment=settings.ENVIRONMENT.value,
        debug=settings.DEBUG,
        log_level=settings.LOG_LEVEL,
    )

    # Outbound HTTP client for /api/v1/ai/* proxying to the ai-agent
    # microservice — one pooled client for the process lifetime.
    app.state.ai_client = httpx.AsyncClient(
        base_url=settings.AI_AGENT_URL,
        timeout=settings.AI_AGENT_TIMEOUT_SECONDS,
    )

    # Startup verification — fail-fast: any failure raises StartupError and
    # the process exits immediately (orchestrator restarts the pod).
    await readiness.verify_startup_dependencies()
    readiness.mark_ready()
    logger.info("service.started", environment=settings.ENVIRONMENT.value)

    # Payroll automation worker (HR-AUT-001): a background asyncio loop that
    # drains the queue. Disabled under the test environment so integration
    # tests drive process_once() directly through POST /ai/payroll/tick.
    if settings.PAYROLL_AUTO_WORKER_ENABLED and settings.ENVIRONMENT != Environment.TEST:
        from core.db.session import async_session_factory
        from core.features.payroll_automation.worker import PayrollAutomationWorker

        app.state.payroll_automation_worker = PayrollAutomationWorker(
            async_session_factory,
            poll_seconds=settings.PAYROLL_AUTO_POLL_SECONDS,
            max_retries=settings.PAYROLL_AUTO_MAX_RETRIES,
            items_per_tick=settings.PAYROLL_AUTO_ITEMS_PER_TICK,
        )
        app.state.payroll_automation_worker.start()
    else:
        app.state.payroll_automation_worker = None

    # Graceful shutdown: uvicorn owns SIGTERM/SIGINT handling; on signal it
    # runs this context manager's exit, closing the readiness gate, the AI
    # client and the DB engine so in-flight work can drain cleanly.
    yield

    readiness.mark_stopping()
    logger.info("service.stopping", environment=settings.ENVIRONMENT.value)

    from core.db.session import engine

    worker = getattr(app.state, "payroll_automation_worker", None)
    if worker is not None:
        await worker.stop()
    await app.state.ai_client.aclose()
    await engine.dispose()
