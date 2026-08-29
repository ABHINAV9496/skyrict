"""Domain dataclasses for the payroll automation batch engine.

Thin, immutable projections of the ``ai_payroll_batch_runs`` /
``ai_payroll_batch_items`` rows that repositories return to the service — keeps
the service layer DB-agnostic (unit-testable without ORM objects) and mirrors
how the payroll feature's repositories project entities.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PayrollBatchRun:
    """One batch run — enqueued, processing, or terminal."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    source: str
    source_ref: str
    status: str
    dry_run: bool
    claimed_by: str | None = None
    preflight: dict[str, object] | None = None
    totals: dict[str, object] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class PayrollBatchItem:
    """One per-employee work item within a batch."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    batch_id: uuid.UUID
    employee_id: uuid.UUID
    status: str
    retry_count: int = 0
    error_text: str | None = None


__all__ = ["PayrollBatchItem", "PayrollBatchRun"]
