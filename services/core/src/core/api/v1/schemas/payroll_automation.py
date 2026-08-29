"""Pydantic request/response schemas for the payroll automation API (HR-AUT-001)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PayrollBatchEnqueueRequest(BaseModel):
    """Submit a payroll run for automation; idempotent per run."""

    run_id: uuid.UUID
    dry_run: bool = False


class PayrollBatchOut(BaseModel):
    """Projection of one ``ai_payroll_batch_runs`` row for the API."""

    batch_id: uuid.UUID
    tenant_id: uuid.UUID
    source: str
    source_ref: str
    status: str
    dry_run: bool
    claimed_by: str | None = None
    preflight: dict[str, object] | None = None
    totals: dict[str, object] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PayrollBatchTickOut(BaseModel):
    """Outcome of one manual/CI processing tick."""

    batch_id: uuid.UUID | None = None
    items_processed: int = 0
    status_changed: bool = False


__all__ = [
    "PayrollBatchEnqueueRequest",
    "PayrollBatchOut",
    "PayrollBatchTickOut",
]
