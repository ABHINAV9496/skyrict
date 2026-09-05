"""Postgres implementation of the payroll automation repository.

Atomicity is the whole point: every claim is a single conditional ``UPDATE``
whose subquery selects the best eligible row ``FOR UPDATE SKIP LOCKED`` — two
concurrent workers can never claim the same batch/item, and whichever loses the
race simply gets ``None`` (deterministic "exactly one winner", no ordering
dependence). Progress bookkeeping is written in the same transaction as the item
termination, so a crash between commits leaves the item exactly where it was
(never recomputed if ``done``, re-eligibible if ``failed`` within retry budget).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.features.payroll_automation.constants import (
    BATCH_ABORTED,
    BATCH_PROCESSING,
    BATCH_QUEUED,
    ITEM_DONE,
    ITEM_FAILED,
    ITEM_PENDING,
    ITEM_PROCESSING,
    SOURCE_PAYROLL_RUN,
)
from core.features.payroll_automation.domain import PayrollBatchItem, PayrollBatchRun
from core.features.payroll_automation.models import PayrollBatchItemModel, PayrollBatchRunModel

RunModel = PayrollBatchRunModel
ItemModel = PayrollBatchItemModel


def _to_run(row: PayrollBatchRunModel) -> PayrollBatchRun:
    return PayrollBatchRun(
        id=row.id,
        tenant_id=row.tenant_id,
        source=row.source,
        source_ref=row.source_ref,
        status=row.status,
        dry_run=row.dry_run,
        claimed_by=row.claimed_by,
        preflight=row.preflight,
        totals=row.totals,
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
    )


def _to_item(row: PayrollBatchItemModel) -> PayrollBatchItem:
    return PayrollBatchItem(
        id=row.id,
        tenant_id=row.tenant_id,
        batch_id=row.batch_id,
        employee_id=row.employee_id,
        status=row.status,
        retry_count=row.retry_count,
        error_text=row.error_text,
    )


class PostgresPayrollAutomationRepository:
    """Batch-run persistence backed by the ``ai_payroll_batch_*`` tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    # --- Batch lifecycle ------------------------------------------------------

    async def get_batch(
        self,
        *,
        tenant_id: uuid.UUID,
        source: str,
        source_ref: str,
    ) -> PayrollBatchRun | None:
        row = (
            await self._session.execute(
                sa.select(RunModel).where(
                    RunModel.tenant_id == tenant_id,
                    RunModel.source == source,
                    RunModel.source_ref == source_ref,
                )
            )
        ).scalar_one_or_none()
        return _to_run(row) if row is not None else None

    async def get_batch_by_id(
        self, batch_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> PayrollBatchRun | None:
        row = (
            await self._session.execute(
                sa.select(RunModel).where(
                    RunModel.tenant_id == tenant_id,
                    RunModel.id == batch_id,
                )
            )
        ).scalar_one_or_none()
        return _to_run(row) if row is not None else None

    async def list_batches(
        self,
        *,
        tenant_id: uuid.UUID,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PayrollBatchRun]:
        stmt = sa.select(RunModel).where(RunModel.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(RunModel.status == status)
        stmt = stmt.order_by(RunModel.created_at.desc(), RunModel.id).limit(limit).offset(offset)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_run(row) for row in rows]

    async def create_batch(
        self,
        *,
        tenant_id: uuid.UUID,
        source: str,
        source_ref: str,
        dry_run: bool,
        totals: dict[str, object],
        preflight: dict[str, object] | None = None,
    ) -> PayrollBatchRun:
        row = RunModel(
            tenant_id=tenant_id,
            source=source,
            source_ref=source_ref,
            status=BATCH_QUEUED,
            dry_run=dry_run,
            totals=totals,
            preflight=preflight,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_run(row)

    async def add_items(
        self,
        *,
        batch_id: uuid.UUID,
        tenant_id: uuid.UUID,
        employee_ids: list[uuid.UUID],
    ) -> None:
        """Bulk-insert items, ignoring duplicates on (batch_id, employee_id)."""
        if not employee_ids:
            return
        rows = [
            {"tenant_id": tenant_id, "batch_id": batch_id, "employee_id": employee_id}
            for employee_id in employee_ids
        ]
        stmt = (
            pg_insert(ItemModel)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["batch_id", "employee_id"])
        )
        await self._session.execute(stmt)

    async def claim_next_batch(self, worker_id: str) -> PayrollBatchRun | None:
        """Atomically claim one payroll-run batch — exactly one winner wins.

        A ``queued`` batch is claimed by the first worker that gets to it; a
        ``processing`` batch is resumed only by the worker that already owns
        it (``claimed_by``), so a single worker can checkpoint-drive a batch
        across many ticks while every other worker skips it. Only payroll-run
        batches are claimable (Commit 1 scope); later sources get their own
        producer/consumer. The candidate subquery locks skipped rows, so
        concurrent workers never get the same batch.
        """
        resumed = (RunModel.status == BATCH_PROCESSING) & (RunModel.claimed_by == worker_id)
        claimable = (RunModel.status == BATCH_QUEUED) | resumed
        best_id = (
            sa.select(RunModel.id)
            .where(claimable, RunModel.source == SOURCE_PAYROLL_RUN)
            .order_by(RunModel.created_at, RunModel.id)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        stmt = (
            sa.update(RunModel)
            .where(RunModel.id == best_id)
            .values(
                status=BATCH_PROCESSING,
                claimed_by=worker_id,
                started_at=datetime.now(UTC),
            )
            .returning(RunModel)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_run(row) if row is not None else None

    async def finalize_batch(
        self,
        *,
        batch_id: uuid.UUID,
        tenant_id: uuid.UUID,
        status: str,
        totals: dict[str, object],
        finished_at: object,
    ) -> None:
        await self._session.execute(
            sa.update(RunModel)
            .where(
                RunModel.tenant_id == tenant_id,
                RunModel.id == batch_id,
                RunModel.status == BATCH_PROCESSING,
            )
            .values(status=status, totals=totals, finished_at=finished_at)
        )

    async def abort_batch(
        self,
        *,
        batch_id: uuid.UUID,
        tenant_id: uuid.UUID,
        totals: dict[str, object],
        finished_at: object,
    ) -> PayrollBatchRun:
        stmt = (
            sa.update(RunModel)
            .where(
                RunModel.tenant_id == tenant_id,
                RunModel.id == batch_id,
                RunModel.status.in_([BATCH_QUEUED, BATCH_PROCESSING]),
            )
            .values(status=BATCH_ABORTED, totals=totals, finished_at=finished_at)
            .returning(RunModel)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ValueError(f"batch {batch_id} is not abortable")
        return _to_run(row)

    async def reset_batch(
        self,
        *,
        batch_id: uuid.UUID,
        tenant_id: uuid.UUID,
        dry_run: bool,
        totals: dict[str, object],
        preflight: dict[str, object],
    ) -> PayrollBatchRun:
        """Re-arm an aborted batch as ``queued`` for a fresh submission.

        The unique ``(tenant_id, source, source_ref)`` index keeps ONE batch row
        per run; when a previous submission was blocked by pre-flight, re-enqueue
        clears its claim/timestamps and stamps the new attempt's config instead
        of inserting a colliding row. Only ``aborted`` rows can be re-armed.
        """
        stmt = (
            sa.update(RunModel)
            .where(
                RunModel.tenant_id == tenant_id,
                RunModel.id == batch_id,
                RunModel.status == BATCH_ABORTED,
            )
            .values(
                status=BATCH_QUEUED,
                claimed_by=None,
                started_at=None,
                finished_at=None,
                dry_run=dry_run,
                totals=totals,
                preflight=preflight,
            )
            .returning(RunModel)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ValueError(f"batch {batch_id} is not aborted and cannot be reset")
        return _to_run(row)

    # --- Item lifecycle -------------------------------------------------------

    async def claim_next_item(
        self,
        *,
        batch_id: uuid.UUID,
        tenant_id: uuid.UUID,
        max_retries: int,
    ) -> PayrollBatchItem | None:
        """Atomically claim the next pending or retry-eligible failed item."""
        best_id = (
            sa.select(ItemModel.id)
            .where(
                ItemModel.tenant_id == tenant_id,
                ItemModel.batch_id == batch_id,
                sa.or_(
                    ItemModel.status == ITEM_PENDING,
                    sa.and_(
                        ItemModel.status == ITEM_FAILED,
                        ItemModel.retry_count < max_retries,
                    ),
                ),
            )
            .order_by(ItemModel.created_at, ItemModel.id)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        stmt = (
            sa.update(ItemModel)
            .where(ItemModel.id == best_id)
            .values(status=ITEM_PROCESSING)
            .returning(ItemModel)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_item(row) if row is not None else None

    async def mark_item_done(self, item_id: uuid.UUID, *, tenant_id: uuid.UUID) -> None:
        await self._session.execute(
            sa.update(ItemModel)
            .where(ItemModel.tenant_id == tenant_id, ItemModel.id == item_id)
            .values(status=ITEM_DONE)
        )

    async def mark_item_failed(
        self,
        item_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        retry_count: int,
        error_text: str,
    ) -> None:
        await self._session.execute(
            sa.update(ItemModel)
            .where(ItemModel.tenant_id == tenant_id, ItemModel.id == item_id)
            .values(status=ITEM_FAILED, retry_count=retry_count, error_text=error_text[:1024])
        )

    async def claimable_item_count(
        self,
        *,
        batch_id: uuid.UUID,
        tenant_id: uuid.UUID,
        max_retries: int,
    ) -> int:
        row = (
            await self._session.execute(
                sa.select(sa.func.count(ItemModel.id)).where(
                    ItemModel.tenant_id == tenant_id,
                    ItemModel.batch_id == batch_id,
                    sa.or_(
                        ItemModel.status == ITEM_PENDING,
                        sa.and_(
                            ItemModel.status == ITEM_FAILED,
                            ItemModel.retry_count < max_retries,
                        ),
                    ),
                )
            )
        ).scalar_one()
        return int(row)

    async def update_totals(
        self,
        *,
        batch_id: uuid.UUID,
        tenant_id: uuid.UUID,
        totals: dict[str, object],
    ) -> None:
        await self._session.execute(
            sa.update(RunModel)
            .where(
                RunModel.tenant_id == tenant_id,
                RunModel.id == batch_id,
                sa.not_(RunModel.status.in_(["completed", "failed", "aborted"])),
            )
            .values(totals=totals)
        )


__all__ = ["PostgresPayrollAutomationRepository"]
