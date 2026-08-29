"""Batch engine service — enqueue, checkpoint processing, resume, finalization.

Orchestrates the ``ai_payroll_batch_*`` tables on top of the payroll feature's
per-employee seam (:meth:`PayrollService.compute_single`). Each per-item
claim→compute→mark commit is a durable checkpoint: a crash between commits
leaves the item exactly where it was, and failed items re-enter the claim set
through their retry budget (``MAX_RETRIES = 2``) until they are terminal.

Fault semantics (carrier of the checkout-acceptance tests):

* ``PermanentBatchItemError``  — the item can never succeed (injected failure
  in the acceptance check, permanent missing dependency, ...). It is marked
  ``failed`` immediately with ``retry_count`` forced to ``max_retries`` so it
  can never be re-claimed; the batch still finishes ``completed`` with the
  failure recorded in ``totals.failed``.
* any other exception — treated as transient. ``retry_count`` advances; while
  it stays below ``max_retries`` the item is re-claimed on a later tick
  (observable as ``totals.retried``). At the budget the item is terminal
  ``failed``.
* concurrency — every claim is an atomic ``FOR UPDATE SKIP LOCKED`` update, so
  even two workers racing can never process the same item twice.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from core.core.audit_service import AuditService
from core.core.tenant_context import TenantContext
from core.domain import entities as ent
from core.features.payroll_automation.constants import (
    BATCH_COMPLETED,
    BATCH_FAILED,
    SOURCE_PAYROLL_RUN,
)
from core.features.payroll_automation.domain import PayrollBatchRun
from core.features.payroll_automation.ports import PayrollAutomationRepositoryPort

logger = logging.getLogger(__name__)


class PermanentBatchItemError(Exception):
    """The item can never succeed; mark it failed without burning retries."""


class PayrollComputePort(Protocol):
    """The payroll-feature seam the batch engine depends on.

    Exactly ``PayrollService``'s relevant methods; protocol-typed so the engine
    is unit-testable with a doubling stub.
    """

    async def get_run(
        self, run_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> ent.PayrollRun | None: ...

    async def is_computable(self, run: ent.PayrollRun) -> bool: ...

    async def get_settings(self, tenant_id: uuid.UUID) -> ent.PayrollSettings | None: ...

    async def active_employees(
        self, run_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Sequence[ent.Employee]: ...

    async def compute_single(
        self,
        *,
        run_id: uuid.UUID,
        employee_id: uuid.UUID,
        tenant_id: uuid.UUID,
        persist: bool = True,
    ) -> tuple[ent.PayrollEntry | None, str | None]: ...

    async def finalize_compute(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None = None,
        skipped: list[dict[str, str]] | None = None,
    ) -> ent.PayrollRun: ...


@dataclass(frozen=True)
class EnqueueResult:
    """Outcome of submitting a run for batch processing."""

    batch: PayrollBatchRun
    employee_count: int


@dataclass(frozen=True)
class ProcessResult:
    """Outcome of one process tick (a partial or complete pass over a batch)."""

    batch_id: uuid.UUID | None = None
    items_processed: int = 0
    status_changed: bool = False


def _empty_totals(employee_count: int) -> dict[str, object]:
    return {
        "total": employee_count,
        "done": 0,
        "failed": 0,
        "skipped": 0,
        "retried": 0,
        "gross": "0",
        "net": "0",
    }


class PayrollAutomationService:
    """Enqueue + checkpoint-resume processing of payroll batch runs."""

    def __init__(
        self,
        repository: PayrollAutomationRepositoryPort,
        payroll: PayrollComputePort,
        audit: AuditService,
        *,
        worker_id: str | None = None,
        max_retries: int = 2,
        items_per_tick: int = 10,
    ) -> None:
        self._repo = repository
        self._payroll = payroll
        self._audit = audit
        self._worker_id = worker_id or f"worker-{uuid.uuid4().hex[:12]}"
        self._max_retries = max_retries
        self._items_per_tick = items_per_tick

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------
    async def enqueue(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None = None,
        dry_run: bool = False,
    ) -> EnqueueResult:
        """Submit a payroll run for batch processing; idempotent per run.

        Returns the existing batch (``recomputed=False``) when the run was
        already enqueued, so PATCH-style retries and recompute submissions are
        safe. Guards: the run must exist and be draft/computed (recomputable),
        and payroll settings must exist.
        """
        run = await self._payroll.get_run(run_id, tenant_id=tenant_id)
        if run is None:
            raise ValueError(f"payroll run {run_id} not found")
        if not await self._payroll.is_computable(run):
            raise ValueError(
                f"payroll run {run_id} is not computable (status={run.status.value})"
            )
        settings = await self._payroll.get_settings(tenant_id)
        if settings is None:
            raise ValueError(f"payroll settings missing for tenant {tenant_id}")

        existing = await self._repo.get_batch(
            tenant_id=tenant_id,
            source=SOURCE_PAYROLL_RUN,
            source_ref=str(run_id),
        )
        if existing is not None:
            return EnqueueResult(batch=existing, employee_count=int(
                (existing.totals or {}).get("total", 0)
            ))

        source_ref = str(run_id)
        roster = await self._payroll.active_employees(run_id, tenant_id=tenant_id)
        employee_ids = [employee.id for employee in roster if employee.id is not None]
        totals = _empty_totals(len(employee_ids))
        batch = await self._repo.create_batch(
            tenant_id=tenant_id,
            source=SOURCE_PAYROLL_RUN,
            source_ref=source_ref,
            dry_run=dry_run,
            totals=totals,
        )
        await self._repo.add_items(
            batch_id=batch.id,
            tenant_id=tenant_id,
            employee_ids=employee_ids,
        )
        await self.commit()
        logger.info(
            "enqueued payroll automation batch %s for run %s (%d employees, dry_run=%s)",
            batch.id,
            run_id,
            len(employee_ids),
            dry_run,
        )
        return EnqueueResult(batch=batch, employee_count=len(employee_ids))

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------
    async def process_once(
        self,
        *,
        worker_id: str | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> ProcessResult:
        """Claim and process work for up to one batch for one tick.

        Exactly-one-winner claim (``FOR UPDATE SKIP LOCKED``) on the batch, then
        a per-item claim→compute→mark loop with a commit after every item (a
        durable checkpoint). When no item is claimable any more the batch is
        finalized — the run transition (unless dry-run) plus the batch's own
        status/totals.
        """
        worker_id = worker_id or self._worker_id
        TenantContext.reset()
        TenantContext.set_user_id(None)

        batch = await self._repo.claim_next_batch(worker_id)
        if batch is None:
            return ProcessResult(batch_id=None, items_processed=0)

        # Make the claim durable independently of the first item's outcome, so a
        # crash here cannot return the batch to the queue for re-claiming.
        await self.commit()

        # The claim is unscoped (the dev role owns the ai_* tables and ignores
        # RLS); every downstream read (payroll runs/entries, erp employees) is
        # RLS-scoped, so pin the tenant context right after the claim.
        TenantContext.set(str(batch.tenant_id))
        tenant_id = batch.tenant_id
        try:
            run_id = (
                uuid.UUID(batch.source_ref) if batch.source == SOURCE_PAYROLL_RUN else None
            )
        except ValueError:
            # Not a payroll-run batch (or a corrupted source_ref): every item
            # fails PermanentBatchItemError below and the batch closes ``failed``
            # explicitly instead of crashing the worker loop.
            run_id = None

        totals = dict(batch.totals or _empty_totals(0))
        skipped: list[dict[str, str]] = []
        items_processed = 0
        status_changed = False
        try:
            while items_processed < self._items_per_tick:
                item = await self._repo.claim_next_item(
                    batch_id=batch.id,
                    tenant_id=tenant_id,
                    max_retries=self._max_retries,
                )
                if item is None:
                    break
                items_processed += 1
                yield_tick = await self._process_item(
                    item_id=item.id,
                    employee_id=item.employee_id,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    retry_count=item.retry_count,
                    dry_run=batch.dry_run,
                    totals=totals,
                    skipped=skipped,
                )
                await self._repo.update_totals(
                    batch_id=batch.id, tenant_id=tenant_id, totals=totals
                )
                await self.commit()
                # A retry-eligible failure re-entered the claim set; defer the
                # remainder of this tick so the retry happens on a LATER tick
                # (a true resume), never microseconds later in the same pass.
                if yield_tick:
                    break

            claimable = await self._repo.claimable_item_count(
                batch_id=batch.id,
                tenant_id=tenant_id,
                max_retries=self._max_retries,
            )
            if claimable == 0:
                await self._finalize_batch(
                    tenant_id=tenant_id,
                    batch=batch,
                    run_id=run_id,
                    totals=totals,
                    skipped=skipped,
                    actor_user_id=actor_user_id,
                )
                status_changed = True
                await self.commit()
        finally:
            TenantContext.reset()
        return ProcessResult(
            batch_id=batch.id,
            items_processed=items_processed,
            status_changed=status_changed,
        )

    async def _process_item(
        self,
        *,
        item_id: uuid.UUID,
        employee_id: uuid.UUID,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID | None,
        retry_count: int,
        dry_run: bool,
        totals: dict[str, object],
        skipped: list[dict[str, str]],
    ) -> bool:
        """Compute one employee; update the running totals and persist the item.

        Returns ``True`` when the item was marked failed but stays inside its
        retry budget — the caller should yield the rest of the tick so the
        retry is picked up on a later tick.
        """
        try:
            if run_id is None:
                raise PermanentBatchItemError(
                    "batch has no payroll run source to compute against"
                )
            entry, reason = await self._payroll.compute_single(
                run_id=run_id,
                employee_id=employee_id,
                tenant_id=tenant_id,
                persist=not dry_run,
            )
        except PermanentBatchItemError as exc:
            totals["failed"] = int(totals.get("failed", 0)) + 1
            await self._mark_failed(
                item_id, tenant_id, retry_count=self._max_retries, error_text=str(exc)[:1024]
            )
            return False
        except Exception as exc:  # transient — burn one retry
            new_retry = retry_count + 1
            if new_retry < self._max_retries:
                totals["retried"] = int(totals.get("retried", 0)) + 1
            else:
                totals["failed"] = int(totals.get("failed", 0)) + 1
            await self._mark_failed(
                item_id, tenant_id, retry_count=new_retry, error_text=f"{type(exc).__name__}: {exc}"
            )
            return new_retry < self._max_retries

        if entry is None:
            totals["skipped"] = int(totals.get("skipped", 0)) + 1
            skipped.append({"employee_id": str(employee_id), "reason": reason or "no entry"})
            await self._repo.mark_item_done(item_id, tenant_id=tenant_id)
            return False
        totals["done"] = int(totals.get("done", 0)) + 1
        totals["gross"] = str(Decimal(totals.get("gross", "0")) + entry.gross.amount)
        totals["net"] = str(Decimal(totals.get("net", "0")) + entry.net.amount)
        await self._repo.mark_item_done(item_id, tenant_id=tenant_id)
        return False

    async def _mark_failed(
        self,
        item_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        retry_count: int,
        error_text: str,
    ) -> None:
        await self._repo.mark_item_failed(
            item_id,
            tenant_id=tenant_id,
            retry_count=retry_count,
            error_text=error_text,
        )

    async def _finalize_batch(
        self,
        *,
        tenant_id: uuid.UUID,
        batch: PayrollBatchRun,
        run_id: uuid.UUID | None,
        totals: dict[str, object],
        skipped: list[dict[str, str]],
        actor_user_id: uuid.UUID | None,
    ) -> None:
        """Close a batch whose items are all terminal.

        For a real (non-dry-run) payroll batch the run itself is finalized via
        :meth:`PayrollService.finalize_compute` (totals, ``draft -> computed``,
        audit, event); a dry-run batch only closes (no run transition). If the
        run transition is refused the batch closes ``failed`` so the outcome is
        explicit.
        """
        try:
            if run_id is not None and not batch.dry_run:
                await self._payroll.finalize_compute(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    skipped=skipped,
                )
        except Exception as exc:  # run refused the transition — explicit failure
            logger.warning("finalize_compute refused for run %s: %s", run_id, exc)
            status = BATCH_FAILED
        else:
            status = BATCH_COMPLETED
        await self._repo.finalize_batch(
            batch_id=batch.id,
            tenant_id=tenant_id,
            status=status,
            totals=dict(totals),
            finished_at=datetime.now(UTC),
        )

    async def batch_status(self, batch_id: uuid.UUID, *, tenant_id: uuid.UUID) -> dict[str, object]:
        """Public projection of a batch for the status endpoint."""
        batch = await self._repo.get_batch_by_id(batch_id, tenant_id=tenant_id)
        if batch is None:
            raise ValueError(f"ai payroll batch {batch_id} not found")
        return {
            "batch_id": str(batch.id),
            "tenant_id": str(batch.tenant_id),
            "source": batch.source,
            "source_ref": batch.source_ref,
            "status": batch.status,
            "dry_run": batch.dry_run,
            "claimed_by": batch.claimed_by,
            "preflight": batch.preflight,
            "totals": batch.totals or {},
            "started_at": batch.started_at.isoformat() if batch.started_at else None,
            "finished_at": batch.finished_at.isoformat() if batch.finished_at else None,
        }

    # ------------------------------------------------------------------
    # Session plumbing (aligned with AuditService.persist / PayrollService)
    # ------------------------------------------------------------------
    async def commit(self) -> None:
        """Persist the in-flight transaction. No-op when the repository doesn't
        manage its own session (unit-test stub)."""
        session = getattr(self._repo, "session", None)
        if session is not None:
            await session.commit()

    async def rollback(self) -> None:
        session = getattr(self._repo, "session", None)
        if session is not None:
            await session.rollback()


__all__ = [
    "EnqueueResult",
    "PayrollAutomationService",
    "PayrollComputePort",
    "PermanentBatchItemError",
    "ProcessResult",
]
