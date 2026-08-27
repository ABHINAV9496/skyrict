"""Daily narrator scheduler - APScheduler cron (SKY-63).

Runs the cross-module digest once per day per enabled tenant at a configured
hour/minute in tenant time. The scheduler is optional (disabled by default via
``AI_NARRATOR_SCHEDULER_ENABLED``) and defensive: a single tenant failing never
crashes the cron, and every run is logged.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from typing import TYPE_CHECKING

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from ai_agent.features.narrator.service import NarratorService

logger = structlog.get_logger("ai_agent.narrator_scheduler")

TenantProvider = Callable[[], Awaitable[list[tuple[uuid.UUID, str]]]]
ServiceFactory = Callable[[uuid.UUID, str], Awaitable["NarratorService"]]


class NarratorScheduler:
    """One async cron job producing each enabled tenant's daily digest."""

    def __init__(
        self,
        *,
        tenant_provider: TenantProvider,
        service_factory: ServiceFactory,
        hour: int,
        minute: int,
        timezone: str,
    ) -> None:
        self._tenant_provider = tenant_provider
        self._service_factory = service_factory
        self._hour = hour
        self._minute = minute
        self._timezone = timezone
        self._scheduler: AsyncIOScheduler | None = None

    def start(self) -> None:
        if self._scheduler is not None:
            return
        scheduler = AsyncIOScheduler(timezone=self._timezone)
        scheduler.add_job(
            self._run_all,
            CronTrigger(hour=self._hour, minute=self._minute, timezone=self._timezone),
            id="narrator_daily",
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )
        scheduler.start()
        self._scheduler = scheduler
        logger.info("narrator_scheduler.started", hour=self._hour, minute=self._minute)

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("narrator_scheduler.stopped")

    async def _run_all(self) -> None:
        tenants = await self._tenant_provider()
        for tenant_id, _slug in tenants:
            try:
                service = await self._service_factory(tenant_id, _slug)
                await service.digest(
                    tenant_id=tenant_id,
                    user_id=None,
                    as_of=date.today(),
                    force_refresh=False,
                )
            except Exception:
                logger.exception("narrator_scheduler.tenant_failed", tenant_id=tenant_id)
