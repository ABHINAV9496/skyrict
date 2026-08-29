"""Payroll automation feature (HR-AUT-001) — batch runs + checkpoint processing.

The feature owns the ``ai_payroll_batch_runs`` / ``ai_payroll_batch_items``
tables (migration 0026), the claim/process/resume engine, an in-process worker
loop, and the ``/api/v1/ai/payroll/*`` routes. Per-employee compute delegates to
``PayrollService.compute_single`` (the commit-1 seam) so money logic stays in
the payroll feature.
"""

from __future__ import annotations

from core.features.payroll_automation.service import (
    EnqueueResult,
    PayrollAutomationService,
    PermanentBatchItemError,
    ProcessResult,
)

__all__ = [
    "EnqueueResult",
    "PayrollAutomationService",
    "PermanentBatchItemError",
    "ProcessResult",
]
