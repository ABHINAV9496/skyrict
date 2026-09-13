"""In-process approval SLA escalation worker (SKY-92, escalation commit).

A single background asyncio task walks every tenant with at least one
``pending`` approval instance once per poll and escalates the current steps
whose ``sla_due_at`` has passed (see :class:`ApprovalEscalationService` for
the nudge-not-decision contract).

The worker sets the request-scoped ``TenantContext`` per tenant so RLS binds
each escalation to that tenant's rows (the owner role bypasses RLS, but the
context keeps the worker's semantic identical to request-path behaviour).
Each tenant's pass runs in its own session/transaction so a failure for one
tenant never rolls back another's.

The worker is owned by the core app lifespan (``api/lifespan.py``) and guarded
by ``APPROVAL_ESCALATION_WORKER_ENABLED`` + non-test environment; ``core
approval-escalation run`` is the manual/CI equivalent that drives
``process_all`` without the background loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.core.tenant_context import TenantContext
from core.features.approval_workflow.escalation import ApprovalEscalationService
from core.features.approval_workflow.instance_repository import (
    ApprovalWorkflowInstanceRepository,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EscalationOutcome:
    """Result of one escalation pass, for the log line and the CLI."""

    tenants_processed: int
    steps_escalated: int


class ApprovalEscalationWorker:
    """Background loop that escalates overdue current steps."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        poll_seconds: float = 3600.0,
        steps_per_pass: int = 200,
    ) -> None:
        self._session_factory = session_factory
        self._poll_seconds = poll_seconds
        self._steps_per_pass = steps_per_pass
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
            name="approval-escalation-worker",
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
            "approval.escalation.worker.started",
            extra={"worker_id": self._worker_id, "steps_per_pass": self._steps_per_pass},
        )
        try:
            while not self._stop.is_set():
                try:
                    outcome = await self.process_all()
                    if outcome.steps_escalated:
                        logger.info(
                            "approval.escalation.worker.pass",
                            extra={"worker_id": self._worker_id, **outcome.__dict__},
                        )
                except Exception:
                    logger.exception(
                        "approval.escalation.worker.pass_failed",
                        extra={"worker_id": self._worker_id},
                    )
                await asyncio.sleep(self._poll_seconds)
        finally:
            logger.info(
                "approval.escalation.worker.stopped",
                extra={"worker_id": self._worker_id},
            )

    async def process_all(self) -> EscalationOutcome:
        """Run one full escalation pass across every pending-instance tenant."""
        async with self._session_factory() as session:
            tenant_ids = await ApprovalWorkflowInstanceRepository(session).list_pending_tenant_ids()

        escalated_total = 0
        for tenant_id in tenant_ids:
            tid = str(tenant_id)
            async with self._session_factory() as session:
                TenantContext.set(tid)
                try:
                    repository = ApprovalWorkflowInstanceRepository(session)
                    escalated = await ApprovalEscalationService(repository).escalate_overdue(
                        tenant_id=tenant_id,
                        limit=self._steps_per_pass,
                    )
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    TenantContext.reset()
            escalated_total += escalated

        return EscalationOutcome(
            tenants_processed=len(tenant_ids),
            steps_escalated=escalated_total,
        )


__all__ = ["ApprovalEscalationWorker", "EscalationOutcome"]
