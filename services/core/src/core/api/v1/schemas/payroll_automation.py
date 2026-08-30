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
    schedules_fired: int = 0


class PayrollBatchListItem(BaseModel):
    """One row of the calendar/batches list (Commit 3 calendar view)."""

    batch_id: uuid.UUID
    tenant_id: uuid.UUID
    source: str
    source_ref: str
    status: str
    dry_run: bool
    totals: dict[str, object] = Field(default_factory=dict)
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PayrollScheduleIn(BaseModel):
    """Create/update payload for a recurring payroll submission (§5.8)."""

    name: str | None = None
    cron_expression: str = Field(..., examples=["0 18 1 * *"])
    enabled: bool = True


class PayrollScheduleOut(BaseModel):
    """Projection of one ``ai_payroll_schedules`` row."""

    schedule_id: uuid.UUID
    tenant_id: uuid.UUID
    name: str | None = None
    cron_expression: str
    enabled: bool
    last_fired_at: datetime | None = None
    next_run_at: datetime | None = None


class PayrollNotificationOut(BaseModel):
    """Projection of one ``ai_payroll_notifications`` row."""

    notification_id: uuid.UUID
    recipient_user_id: uuid.UUID
    event_type: str
    in_app: bool
    email_stub: bool
    subject: str
    body: str
    batch_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    created_at: datetime | None = None


class PayrollPreferencesIn(BaseModel):
    """Delivery-preference update (per user, self-scoped)."""

    in_app_on: bool = True
    email_on: bool = False


class PayrollPreferencesOut(BaseModel):
    """Merged delivery preference (defaults when no row exists)."""

    user_id: uuid.UUID
    in_app_on: bool
    email_on: bool


__all__ = [
    "PayrollBatchEnqueueRequest",
    "PayrollBatchListItem",
    "PayrollBatchOut",
    "PayrollBatchTickOut",
    "PayrollNotificationOut",
    "PayrollPreferencesIn",
    "PayrollPreferencesOut",
    "PayrollScheduleIn",
    "PayrollScheduleOut",
]
