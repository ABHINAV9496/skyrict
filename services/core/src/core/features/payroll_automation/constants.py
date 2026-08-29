"""Batch status constants for the payroll automation engine (HR-AUT-001).

Kept as string literals in one place (mirroring ``core.core.constants`` for the
payroll feature) so the ORM models, repository SQL, service transitions and
schemas all agree. Values must stay in lockstep with migration 0026's check
constraints.
"""

from __future__ import annotations

# --- Batch run lifecycle ---
BATCH_QUEUED = "queued"
BATCH_PROCESSING = "processing"
BATCH_COMPLETED = "completed"
BATCH_FAILED = "failed"
BATCH_ABORTED = "aborted"

# --- Per-item lifecycle ---
ITEM_PENDING = "pending"
ITEM_PROCESSING = "processing"
ITEM_DONE = "done"
ITEM_FAILED = "failed"

# The idempotency source for payroll batch runs. A run may be recomputed, so
# every submitted run-ref (re)creates the batch keyed on (source, source_ref).
SOURCE_PAYROLL_RUN = "payroll_run"

__all__ = [
    "BATCH_ABORTED",
    "BATCH_COMPLETED",
    "BATCH_FAILED",
    "BATCH_PROCESSING",
    "BATCH_QUEUED",
    "ITEM_DONE",
    "ITEM_FAILED",
    "ITEM_PENDING",
    "ITEM_PROCESSING",
    "SOURCE_PAYROLL_RUN",
]
