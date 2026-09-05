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
    created_at: datetime | None = None


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


@dataclass(frozen=True)
class PayrollNotification:
    """A post-commit notification row — payslip-ready or admin digest.

    ``dedupe_key`` is unique per ``(tenant_id, recipient_user_id)`` so the
    orchestrator is idempotent: re-running it cannot duplicate a delivery
    (the HR-AUT-001 acceptance criterion "each employee holds exactly one
    notification row").
    """

    tenant_id: uuid.UUID
    recipient_user_id: uuid.UUID
    event_type: str
    dedupe_key: str
    subject: str
    body: str
    in_app: bool = True
    email_stub: bool = False
    batch_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    id: uuid.UUID | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class PayrollNotificationPref:
    """One employee's delivery preference.

    Absence of a row means the defaults (in-app ON, email OFF); this dataclass
    carries the merged view so callers never branch on "is there a row".
    """

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    in_app_on: bool = True
    email_on: bool = False


@dataclass(frozen=True)
class PayrollSchedule:
    """A per-tenant recurring submission (cron) for payroll batch runs.

    ``next_run_at`` is derived from the cron expression; when a worker tick
    finds ``next_run_at <= now`` on an enabled schedule it creates (or reuses)
    the payroll run for the last fully-elapsed calendar month and submits it.
    """

    tenant_id: uuid.UUID
    cron_expression: str
    enabled: bool = True
    name: str | None = None
    last_fired_at: datetime | None = None
    next_run_at: datetime | None = None
    id: uuid.UUID | None = None


__all__ = [
    "PayrollBatchItem",
    "PayrollBatchRun",
    "PayrollNotification",
    "PayrollNotificationPref",
    "PayrollSchedule",
]
