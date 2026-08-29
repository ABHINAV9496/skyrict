"""In-process payroll automation worker (HR-AUT-001).

A single background asyncio task polls the queue (``ai_payroll_batch_runs``),
claiming exactly one eligible batch per tick (``FOR UPDATE SKIP LOCKED``) and
processing its per-employee items with a durable commit after each one. The
worker builds its own per-tick :class:`PayrollAutomationService` on a fresh
session, so its commits and RLS context are independent of any request.

The worker is owned by the core app lifespan (``api/lifespan.py``) and guarded
by ``PAYROLL_AUTO_WORKER_ENABLED`` + non-test environment; ``POST /ai/payroll/
tick`` is the manual/CI equivalent that drives ``process_once`` without the
background loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.features.payroll_automation.repository import PostgresPayrollAutomationRepository
from core.features.payroll_automation.service import PayrollAutomationService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TickOutcome:
    """Result of one worker tick, for the log line and future telemetry."""

    batch_id: str | None
    items_processed: int
    status_changed: bool


class PayrollAutomationWorker:
    """Background loop that drains the payroll automation queue."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        poll_seconds: float = 0.25,
        max_retries: int = 2,
        items_per_tick: int = 10,
    ) -> None:
        self._session_factory = session_factory
        self._poll_seconds = poll_seconds
        self._max_retries = max_retries
        self._items_per_tick = items_per_tick
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
            name="payroll-automation-worker",
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
        logger.info("payroll.automation.worker.started", extra={"worker_id": self._worker_id})
        try:
            while not self._stop.is_set():
                try:
                    outcome = await self._tick()
                    if outcome.items_processed or outcome.status_changed:
                        logger.info(
                            "payroll.automation.worker.tick",
                            extra={"worker_id": self._worker_id, **outcome.__dict__},
                        )
                except Exception:
                    logger.exception(
                        "payroll.automation.worker.tick_failed",
                        extra={"worker_id": self._worker_id},
                    )
                await asyncio.sleep(self._poll_seconds)
        finally:
            logger.info("payroll.automation.worker.stopped", extra={"worker_id": self._worker_id})

    async def _tick(self) -> TickOutcome:
        async with self._session_factory() as session:
            service = self._build_service(session)
            try:
                result = await service.process_once(worker_id=self._worker_id)
            except Exception:
                await session.rollback()
                raise
        return TickOutcome(
            batch_id=str(result.batch_id) if result.batch_id else None,
            items_processed=result.items_processed,
            status_changed=result.status_changed,
        )

    def _build_service(self, session: AsyncSession) -> PayrollAutomationService:
        from core.api.deps import make_core_audit_service, make_payroll_service

        return PayrollAutomationService(
            repository=PostgresPayrollAutomationRepository(session),
            payroll=make_payroll_service(session),
            audit=make_core_audit_service(session),
            worker_id=self._worker_id,
            max_retries=self._max_retries,
            items_per_tick=self._items_per_tick,
        )


__all__ = ["PayrollAutomationWorker"]
