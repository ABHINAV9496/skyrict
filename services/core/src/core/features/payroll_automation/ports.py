"""Persistence contract for the payroll automation engine.

``PayrollAutomationRepositoryPort`` scopes the batch engine's state machine —
claim (atomic ``FOR UPDATE SKIP LOCKED`` + CAS), per-item progress, totals
bookkeeping, and terminal finalization. Implemented by
:class:`PostgresPayrollAutomationRepository` and injected once at the
composition root (``api/deps.py`` / the worker).
"""

from __future__ import annotations

import uuid
from typing import Protocol

from core.features.payroll_automation.domain import PayrollBatchItem, PayrollBatchRun


class PayrollAutomationRepositoryPort(Protocol):
    """Persistence contract for batch runs and per-employee items."""

    # --- Batch lifecycle ---
    async def get_batch(
        self,
        *,
        tenant_id: uuid.UUID,
        source: str,
        source_ref: str,
    ) -> PayrollBatchRun | None: ...

    async def get_batch_by_id(
        self, batch_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> PayrollBatchRun | None: ...

    async def list_batches(
        self,
        *,
        tenant_id: uuid.UUID,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PayrollBatchRun]: ...

    async def create_batch(
        self,
        *,
        tenant_id: uuid.UUID,
        source: str,
        source_ref: str,
        dry_run: bool,
        totals: dict[str, object],
        preflight: dict[str, object] | None = None,
    ) -> PayrollBatchRun: ...

    async def add_items(
        self,
        *,
        batch_id: uuid.UUID,
        tenant_id: uuid.UUID,
        employee_ids: list[uuid.UUID],
    ) -> None: ...

    async def claim_next_batch(self, worker_id: str) -> PayrollBatchRun | None:
        """Atomically claim one queued batch (exactly one winner).

        SELECT ... FOR UPDATE SKIP LOCKED ordered by ``created_at, id`` inside
        a conditional UPDATE: a concurrent claimer either finds no unlocked
        row (returns ``None``) or loses the CAS. Never returns a batch that is
        already ``processing``, ``completed``, ``failed`` or ``aborted``.
        """
        ...

    async def finalize_batch(
        self,
        *,
        batch_id: uuid.UUID,
        tenant_id: uuid.UUID,
        status: str,
        totals: dict[str, object],
        finished_at: object,
    ) -> None: ...

    async def abort_batch(
        self,
        *,
        batch_id: uuid.UUID,
        tenant_id: uuid.UUID,
        totals: dict[str, object],
        finished_at: object,
    ) -> PayrollBatchRun:
        """Flip a queued (or processing) batch to ``aborted``.

        The pre-flight aborts a batch before any item work: the row is created,
        the preflight evidence is stored, then ``abort_batch`` marks it terminal
        so :meth:`claim_next_batch` can never pick it up. Returns the updated
        run so the caller reflects the terminal state.
        """
        ...

    async def reset_batch(
        self,
        *,
        batch_id: uuid.UUID,
        tenant_id: uuid.UUID,
        dry_run: bool,
        totals: dict[str, object],
        preflight: dict[str, object],
    ) -> PayrollBatchRun:
        """Re-arm an ``aborted`` batch as ``queued`` for a fresh submission.

        The unique ``(tenant_id, source, source_ref)`` index keeps one batch row
        per run, so re-enqueue after a pre-flight block resets this row rather
        than inserting a colliding one.
        """
        ...

    # --- Item lifecycle ---
    async def claim_next_item(
        self,
        *,
        batch_id: uuid.UUID,
        tenant_id: uuid.UUID,
        max_retries: int,
    ) -> PayrollBatchItem | None:
        """Atomically claim the next pending (or retry-eligible failed) item."""
        ...

    async def mark_item_done(self, item_id: uuid.UUID, *, tenant_id: uuid.UUID) -> None: ...

    async def mark_item_failed(
        self,
        item_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        retry_count: int,
        error_text: str,
    ) -> None: ...

    async def claimable_item_count(
        self,
        *,
        batch_id: uuid.UUID,
        tenant_id: uuid.UUID,
        max_retries: int,
    ) -> int:
        """Number of items still pending or within retry budget (0 == all terminal)."""
        ...

    async def update_totals(
        self,
        *,
        batch_id: uuid.UUID,
        tenant_id: uuid.UUID,
        totals: dict[str, object],
    ) -> None: ...


__all__ = ["PayrollAutomationRepositoryPort"]
