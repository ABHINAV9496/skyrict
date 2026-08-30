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

Background jobs (SKY-68): suggestion expiry, anomaly auto-close, and anomaly
scan run as asyncio tasks started after provider init and cancelled on shutdown.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ai_agent.api import readiness
from ai_agent.core.config import settings
from ai_agent.core.llm_router import LlmRouter
from ai_agent.core.logging import configure_logging, get_logger
from ai_agent.core.providers import build_providers_from_settings


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

    # Provider chain: built ONCE at startup; an unknown provider key raises
    # StartupError and refuses boot. Zero providers is a VALID configuration -
    # AI endpoints then degrade to typed 503s while health/readiness stay green.
    llm_router = LlmRouter(build_providers_from_settings(settings))
    app.state.llm_router = llm_router
    logger.info(
        "service.started",
        environment=settings.ENVIRONMENT.value,
        providers_configured=llm_router.provider_count,
    )

# Cross-module narrator (SKY-63): optional daily cron + system agent row.
    # Disabled by default; only starts when explicitly enabled AND a provider is
    # configured (the digest requires the LLM).
    narrator_scheduler: object | None = None
    if settings.NARRATOR_SCHEDULER_ENABLED and llm_router.has_providers:
        from ai_agent.db.agent_registry_repository import AgentRegistryRepository
        from ai_agent.db.session import async_session_factory
        from ai_agent.features.narrator.scheduler import NarratorScheduler

        async def _enabled_tenants() -> list[tuple[uuid.UUID, str]]:
            # Placeholder tenant enumeration. Production wiring lists enabled
            # tenants from the platform directory; keeping it empty here means
            # the cron runs but generates nothing until a tenant provider lands.
            return []

        async def _service_factory(tenant_id: uuid.UUID, slug: str) -> object:
            from sqlalchemy.ext.asyncio import AsyncSession

            from ai_agent.core.audit_service import AuditService
            from ai_agent.db.audit_repository import AiAuditLogRepository
            from ai_agent.db.digest_repository import DigestCacheRepository
            from ai_agent.features.narrator.gateway import HttpCoreGateway
            from ai_agent.features.narrator.service import NarratorService

            session: AsyncSession = async_session_factory()
            return NarratorService(
                gateway=HttpCoreGateway(
                    base_url=str(settings.INVENTORY_SERVICE_URL),
                    bearer_token="",
                    tenant_slug=slug,
                ),
                llm_router=llm_router,
                cache=DigestCacheRepository(session),
                audit=AuditService(AiAuditLogRepository(session)),
                allow_llm=settings.NARRATOR_ALLOW_LLM,
                allow_refresh=True,
            )

        scheduler = NarratorScheduler(
            tenant_provider=_enabled_tenants,
            service_factory=_service_factory,  # type: ignore[arg-type]
            hour=settings.NARRATOR_DAILY_HOUR,
            minute=settings.NARRATOR_DAILY_MINUTE,
            timezone=settings.NARRATOR_SCHEDULER_TIMEZONE,
        )
        scheduler.start()
        narrator_scheduler = scheduler
        try:
            async with async_session_factory() as session:
                await AgentRegistryRepository(session).upsert_system_agent(
                    name="narrator", module="ai_agent.features.narrator"
                )
                await session.commit()
            logger.info("narrator.agent_registered")
        except Exception:
            logger.exception("narrator.agent_registration_failed")

    # --- Background jobs (SKY-68) -----------------------------------------
    bg_tasks: list[asyncio.Task[None]] = []
    from ai_agent.core.jobs.anomaly_autoclose import run_anomaly_autoclose_job
    from ai_agent.core.jobs.anomaly_scan import run_anomaly_scan_job
    from ai_agent.core.jobs.suggestion_expiry import run_suggestion_expiry_job

    bg_tasks.append(asyncio.create_task(run_suggestion_expiry_job()))
    bg_tasks.append(asyncio.create_task(run_anomaly_autoclose_job()))
    bg_tasks.append(asyncio.create_task(run_anomaly_scan_job()))
    logger.info("background_jobs.started", count=len(bg_tasks))

    # Graceful shutdown: uvicorn owns SIGTERM/SIGINT handling; on signal it
    # runs this context manager's exit, closing the readiness gate and the
    # DB/Redis pools so in-flight work can drain cleanly.
    yield

    if narrator_scheduler is not None:
        narrator_scheduler.stop()  # type: ignore[attr-defined]

    # Cancel background jobs before disposing resources.
    for task in bg_tasks:
        task.cancel()
    await asyncio.gather(*bg_tasks, return_exceptions=True)

    readiness.mark_stopping()
    logger.info("service.stopping", environment=settings.ENVIRONMENT.value)

    from ai_agent.core.redis import close_redis
    from ai_agent.db.session import engine

    await close_redis()
    await engine.dispose()
