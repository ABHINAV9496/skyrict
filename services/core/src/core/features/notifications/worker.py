"""In-process notification batching worker (SKY-93).

A single background asyncio task collapses each tenant's burst of low/medium
notifications into digests once per poll (see :class:`NotificationBatcher`
for the collapse contract).

The worker mirrors the approval-escalation worker:

- The request-scoped ``TenantContext`` is set per tenant so RLS binds each
  pass to that tenant's rows (the owner role bypasses RLS, but the context
  keeps the worker's semantics identical to request-path behaviour).
- Each tenant's pass runs in its own session/transaction so a failure for one
  tenant never rolls back another's; a pass-level exception is logged with
  ``exc_info`` and the loop continues.
- ``process_all`` is the manual/CI equivalent (``core notification batch``)
  that drives one pass without waiting on the poll cadence.

Window semantics: the window is ``[now - WINDOW_MINUTES, now]`` computed at
the top of each pass. Digests embed the window start in their dedupe key, so
re-running a pass (or crashing between digest insert and member suppression)
is idempotent.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.core.config import settings
from core.core.tenant_context import TenantContext
from core.features.notifications.batching import NotificationBatcher
from core.features.notifications.repository import NotificationEventRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BatchOutcome:
    """Result of one batching pass, for the log line and the CLI."""

    tenants_processed: int
    digests_created: int
    members_suppressed: int


def _now_utc() -> datetime:
    return datetime.now(UTC)


class NotificationBatchingWorker:
    """Background loop that digests low/medium notification bursts."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        poll_seconds: float | None = None,
        window_minutes: int | None = None,
        min_count: int | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._poll_seconds = (
            settings.NOTIF_BATCH_POLL_SECONDS if poll_seconds is None else poll_seconds
        )
        self._window_minutes = (
            settings.NOTIF_BATCH_WINDOW_MINUTES if window_minutes is None else window_minutes
        )
        self._min_count = settings.NOTIF_BATCH_MIN_COUNT if min_count is None else min_count
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._worker_id = f"core-{socket.gethostname()}-{os.getpid()}"

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Begin the background polling loop (idempotent)."""
        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run_loop(),
            name="notification-batching-worker",
        )

    async def stop(self, *, timeout: float = 5.0) -> None:
        """Signal the loop to stop and await it (cancels on timeout)."""
        self._stop.set()
        task, self._task = self._task, None
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run_loop(self) -> None:
        logger.info(
            "notifications.batch.worker.started",
            extra={
                "worker_id": self._worker_id,
                "poll_seconds": self._poll_seconds,
                "window_minutes": self._window_minutes,
            },
        )
        try:
            while not self._stop.is_set():
                try:
                    outcome = await self.process_all()
                    if outcome.digests_created:
                        logger.info(
                            "notifications.batch.worker.pass",
                            extra={"worker_id": self._worker_id, **outcome.__dict__},
                        )
                except Exception:
                    logger.exception(
                        "notifications.batch.worker.pass_failed",
                        extra={"worker_id": self._worker_id},
                    )
                await asyncio.sleep(self._poll_seconds)
        finally:
            logger.info(
                "notifications.batch.worker.stopped",
                extra={"worker_id": self._worker_id},
            )

    async def process_all(self) -> BatchOutcome:
        """Run one batching pass across every tenant with candidates."""
        async with self._session_factory() as session:
            tenant_ids = await NotificationEventRepository(session).list_active_tenant_ids()

        now = _now_utc()
        window_start = now - timedelta(minutes=self._window_minutes)

        digest_total = 0
        suppressed_total = 0
        for tenant_id in tenant_ids:
            tid = str(tenant_id)
            async with self._session_factory() as session:
                TenantContext.set(tid)
                try:
                    batcher = NotificationBatcher(session)
                    outcome = await batcher.batch_tenant(
                        tenant_id=tenant_id,
                        window_start=window_start,
                        window_end=now,
                        min_count=self._min_count,
                    )
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    TenantContext.reset()
            digest_total += outcome["digests"]
            suppressed_total += outcome["suppressed"]

        return BatchOutcome(
            tenants_processed=len(tenant_ids),
            digests_created=digest_total,
            members_suppressed=suppressed_total,
        )


__all__ = ["BatchOutcome", "NotificationBatchingWorker"]
