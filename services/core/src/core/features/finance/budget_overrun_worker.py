"""In-process budget overrun worker (SKY-85).

A background asyncio task that walks every tenant with at least one ``active``
budget once per poll and emits a notification for each budget line whose net
POSTED fiscal-year activity exceeds the planned amount. This is the proactive
side of the budgets feature: the read-side variance flags an overrun only when
someone opens the page, so this worker makes "someone went over budget" a
notification-center event without anyone having to ask.

The dedupe key ``budget_overrun:{budget_id}:{account_code}`` delivers exactly
once per line crossing regardless of how often the loop runs. Severity is
``HIGH`` for lines over the plan; categorisation uses the registered
``finance`` category routed to holders of ``erp.finance.read``.

The worker sets the request-scoped ``TenantContext`` per tenant so RLS binds
each emission to that tenant's rows. Each tenant's pass runs in its own
session/transaction so a failure for one tenant never rolls back another's.

Owned by the core app lifespan (``api/lifespan.py``) and guarded by
``FINANCE_BUDGET_OVERRUN_WORKER_ENABLED`` + non-test environment; ``core
budget-overrun run`` is the manual/CI equivalent that drives ``process_all``
without the background loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.core.permissions import ERP_FINANCE_READ
from core.core.tenant_context import TenantContext
from core.domain.entities import Budget
from core.domain.value_objects import BudgetStatus
from core.features.finance.repository import FinanceRepository
from core.features.notifications.domain import (
    NotificationDraft,
    NotificationSeverity,
    RecipientSpec,
)
from core.features.notifications.producer import NotificationProducer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BudgetOverrunOutcome:
    """Result of one overrun pass, for the log line and the CLI."""

    tenants_processed: int
    budgets_checked: int
    overruns_notified: int


def _planned_by_code(budget: Budget) -> dict[str, Decimal]:
    return {line.account_code: line.amount for line in budget.lines}


class BudgetOverrunWorker:
    """Background loop that notifies active-budget line overruns."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        poll_seconds: float = 3600.0,
    ) -> None:
        self._session_factory = session_factory
        self._poll_seconds = poll_seconds
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
            name="budget-overrun-worker",
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
            "budget.overrun.worker.started",
            extra={"worker_id": self._worker_id},
        )
        try:
            while not self._stop.is_set():
                try:
                    outcome = await self.process_all()
                    if outcome.overruns_notified:
                        logger.info(
                            "budget.overrun.worker.pass",
                            extra={"worker_id": self._worker_id, **outcome.__dict__},
                        )
                except Exception:
                    logger.exception(
                        "budget.overrun.worker.pass_failed",
                        extra={"worker_id": self._worker_id},
                    )
                await asyncio.sleep(self._poll_seconds)
        finally:
            logger.info(
                "budget.overrun.worker.stopped",
                extra={"worker_id": self._worker_id},
            )

    async def process_all(self) -> BudgetOverrunOutcome:
        """Run one full overrun scan across every tenant with an active budget."""
        async with self._session_factory() as session:
            tenant_ids = await FinanceRepository(session).list_active_budget_tenant_ids()

        budgets_checked = 0
        overruns_notified = 0
        for tenant_id in tenant_ids:
            tid = str(tenant_id)
            async with self._session_factory() as session:
                TenantContext.set(tid)
                try:
                    repo = FinanceRepository(session)
                    budgets = await repo.list_budgets(tenant_id, status=BudgetStatus.ACTIVE.value)
                    for budget in budgets:
                        budgets_checked += 1
                        actuals = await repo.posted_totals_by_code(
                            tenant_id,
                            date(budget.fiscal_year, 1, 1),
                            date(budget.fiscal_year, 12, 31),
                        )
                        overruns_notified += await self._emit_overruns(
                            session, tenant_id, budget, actuals
                        )
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    TenantContext.reset()
        return BudgetOverrunOutcome(
            tenants_processed=len(tenant_ids),
            budgets_checked=budgets_checked,
            overruns_notified=overruns_notified,
        )

    async def _emit_overruns(
        self,
        session: AsyncSession,
        tenant_id: object,
        budget: Budget,
        actuals: dict[str, Decimal],
    ) -> int:
        producer = NotificationProducer(session)
        notified = 0
        for line in budget.lines:
            actual = actuals.get(line.account_code, Decimal("0"))
            if actual <= line.amount or line.amount <= Decimal("0"):
                continue
            draft = NotificationDraft(
                dedupe_key=f"budget_overrun:{budget.id}:{line.account_code}",
                event_type="finance.budget_overrun",
                category="finance",
                module="finance",
                severity=NotificationSeverity.HIGH,
                title=f"Budget overrun: {budget.name}",
                body=(
                    f"'{line.account_code}' has spent {actual} of the planned "
                    f"{line.amount} in FY{budget.fiscal_year}."
                ),
                recipients=RecipientSpec.from_permissions(ERP_FINANCE_READ),
                relevance_key=ERP_FINANCE_READ,
                payload={
                    "budget_id": str(budget.id),
                    "account_code": line.account_code,
                    "actual": str(actual),
                    "planned": str(line.amount),
                    "fiscal_year": budget.fiscal_year,
                },
            )
            try:
                outcome = await producer.emit(draft)
            except Exception:
                logger.exception(
                    "budget.overrun.emit_failed",
                    extra={
                        "tenant_id": str(tenant_id),
                        "budget_id": str(budget.id),
                        "account_code": line.account_code,
                    },
                )
                continue
            if not outcome.deduped:
                notified += 1
        return notified


__all__ = ["BudgetOverrunOutcome", "BudgetOverrunWorker"]
