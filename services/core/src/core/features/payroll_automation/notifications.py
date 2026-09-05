"""Post-commit payroll notification orchestrator (HR-AUT-001, Commit 3).

Fanned out once a batch reaches a terminal state:

* ``payslip_ready`` — fires PER-EMPLOYEE when the payslip is approved
  (``PayrollService.approve_payslip`` 0030 delivery-gate), routed to the
  employee's linked identity user and by their own delivery preference. A
  missing preference row means the defaults (in-app ON, email OFF);
  ``email_stub`` is set when the user opted in. Employees without a linked
  user get no row (documented: in-app delivery needs a portal account). This
  no longer fires at batch-complete — approval gates employee delivery.
* ``payroll_batch_digest`` — for completed AND failed batches, one row per
  payroll admin (holders of ``erp.payroll.ai.read``) carrying totals and the
  failure list (still fires at batch terminal state).

Dedupe: ``(tenant_id, recipient_user_id, dedupe_key)`` is unique, and every
insert is ``ON CONFLICT DO NOTHING`` — re-running the orchestrator (or
re-approving the same version) inserts nothing, which is exactly the acceptance
criterion "each employee holds exactly one notification row".
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from core.core.audit_events import PAYROLL_AUTO_NOTIFICATIONS_SENT
from core.core.audit_service import AuditService
from core.core.permissions import ERP_PAYROLL_AI_READ
from core.features.payroll_automation.constants import (
    BATCH_COMPLETED,
    BATCH_FAILED,
    EVENT_PAYROLL_BATCH_DIGEST,
    EVENT_PAYSLIP_READY,
)
from core.features.payroll_automation.domain import (
    PayrollBatchRun,
    PayrollNotification,
    PayrollNotificationPref,
)

logger = logging.getLogger(__name__)


class PayrollNotificationRepositoryPort(Protocol):
    """Persistence contract for the orchestrator (implemented by
    :class:`PostgresPayrollNotificationRepository`)."""

    async def done_employee_ids(
        self, batch_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> list[uuid.UUID]: ...

    async def employee_user_ids(
        self, tenant_id: uuid.UUID, employee_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, uuid.UUID | None]: ...

    async def prefs_for_users(
        self, tenant_id: uuid.UUID, user_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, PayrollNotificationPref]: ...

    async def user_ids_with_permission(
        self, tenant_id: uuid.UUID, *, permission: str = ERP_PAYROLL_AI_READ
    ) -> list[uuid.UUID]: ...

    async def failed_item_errors(
        self, batch_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> list[dict[str, str]]: ...

    async def insert_notifications(
        self,
        *,
        tenant_id: uuid.UUID,
        notifications: Sequence[PayrollNotification],
    ) -> int: ...

    async def get_pref(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> PayrollNotificationPref: ...

    async def upsert_pref(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        in_app_on: bool,
        email_on: bool,
    ) -> PayrollNotificationPref: ...

    async def list_notifications(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID | None = None,
        event_type: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[PayrollNotification]: ...


class PayrollNotificationOrchestrator:
    """Create the notification rows a terminal batch deserves (idempotently)."""

    def __init__(
        self,
        repository: PayrollNotificationRepositoryPort,
        audit: AuditService | None = None,
    ) -> None:
        self._repo = repository
        self._audit = audit

    async def record_batch_notifications(
        self,
        *,
        tenant_id: uuid.UUID,
        batch: PayrollBatchRun,
        status: str,
        run_id: uuid.UUID | None,
        totals: dict[str, Any],
    ) -> int:
        """Record every notification a terminal batch warrants.

        Returns the number of rows actually inserted (0 when the batch was
        already notified — the dedupe made this a no-op, or the batch deserves
        nothing: dry-run, aborted, or still in flight).

        Only the admin digest fans out here. ``payslip_ready`` is delivered
        per-employee on payslip approval (0030 delivery-gate), so a completed
        batch does not itself email any employee.
        """
        if batch.dry_run or status not in (BATCH_COMPLETED, BATCH_FAILED):
            return 0
        inserted = await self._admin_digests(
            tenant_id=tenant_id,
            batch_id=batch.id,
            run_id=run_id,
            status=status,
            totals=totals,
        )
        if inserted:
            logger.info(
                "payroll.automation.notifications.recorded",
                extra={
                    "tenant_id": str(tenant_id),
                    "batch_id": str(batch.id),
                    "status": status,
                    "rows": inserted,
                },
            )
        if self._audit is not None:
            await self._audit.log(
                action=PAYROLL_AUTO_NOTIFICATIONS_SENT,
                target=f"ai_payroll_batch:{batch.id}",
                tenant_id=tenant_id,
                user_id=None,
                details={
                    "status": status,
                    "rows_inserted": inserted,
                    "dry_run": batch.dry_run,
                },
            )
        return inserted

    async def notify_payslip_approved(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        employee_id: uuid.UUID,
        version: int,
    ) -> None:
        """Deliver one employee's ``payslip_ready`` on payslip approval (0030).

        Implements ``PayslipApprovedNotifierPort`` — the delivery-gate that
        makes "approval gates employee delivery" literal. Idempotent per
        ``(run_id, employee_id, version)`` via the dedupe key, so re-approving
        the same version inserts nothing.
        """
        user_by_employee = await self._repo.employee_user_ids(tenant_id, [employee_id])
        user_id = user_by_employee.get(employee_id)
        if user_id is None:
            # No portal account to receive the in-app notification.
            return
        pref = await self._repo.get_pref(tenant_id, user_id)
        notification = PayrollNotification(
            tenant_id=tenant_id,
            recipient_user_id=user_id,
            event_type=EVENT_PAYSLIP_READY,
            dedupe_key=f"payslip:{run_id}:{employee_id}:{version}",
            in_app=pref.in_app_on,
            email_stub=pref.email_on,
            subject="Your payslip is ready",
            body=f"Your payslip for payroll run {run_id} is ready to view.",
            batch_id=None,
            run_id=run_id,
            employee_id=employee_id,
        )
        await self._repo.insert_notifications(tenant_id=tenant_id, notifications=[notification])
        if self._audit is not None:
            await self._audit.log(
                action=PAYROLL_AUTO_NOTIFICATIONS_SENT,
                target=f"payslip:{employee_id}:{version}",
                tenant_id=tenant_id,
                user_id=user_id,
                details={
                    "event_type": EVENT_PAYSLIP_READY,
                    "run_id": str(run_id),
                    "employee_id": str(employee_id),
                    "version": version,
                },
            )

    async def _admin_digests(
        self,
        *,
        tenant_id: uuid.UUID,
        batch_id: uuid.UUID,
        run_id: uuid.UUID | None,
        status: str,
        totals: dict[str, Any],
    ) -> int:
        admins = await self._repo.user_ids_with_permission(tenant_id)
        if not admins:
            return 0
        total = int(totals.get("total", 0))
        done = int(totals.get("done", 0))
        failed = int(totals.get("failed", 0))
        failures = await self._repo.failed_item_errors(batch_id, tenant_id=tenant_id)
        if failed and not failures:
            failures = [{"error_text": "failed item"} for _ in range(failed)]
        subject = (
            f"Payroll batch {run_id} — {done} of {total} employees completed"
            if failed == 0
            else f"Payroll batch {run_id} — {failed} item(s) failed ({status})"
        )
        body_lines = [
            f"Payroll run {run_id}: batch {batch_id} finished {status}.",
            f"Completed {done} of {total} employees; {failed} failed, "
            f"{int(totals.get('skipped', 0))} skipped.",
        ]
        for failure in failures[:25]:
            body_lines.append(f"- {failure.get('error_text', 'unknown failure')[:4000]}")
        notifications = [
            PayrollNotification(
                tenant_id=tenant_id,
                recipient_user_id=admin_id,
                event_type=EVENT_PAYROLL_BATCH_DIGEST,
                dedupe_key=f"digest:{batch_id}",
                in_app=True,
                email_stub=False,
                subject=subject,
                body="\n".join(body_lines),
                batch_id=batch_id,
                run_id=run_id,
            )
            for admin_id in admins
        ]
        return await self._repo.insert_notifications(
            tenant_id=tenant_id, notifications=notifications
        )

    async def list_notifications(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID | None = None,
        event_type: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Public projections of the notification rows (inbox / calendar view)."""
        rows = await self._repo.list_notifications(
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            event_type=event_type,
            after=after,
            before=before,
            limit=limit,
        )
        return [
            {
                "notification_id": str(row.id),
                "recipient_user_id": str(row.recipient_user_id),
                "event_type": row.event_type,
                "in_app": row.in_app,
                "email_stub": row.email_stub,
                "subject": row.subject,
                "body": row.body,
                "batch_id": str(row.batch_id) if row.batch_id else None,
                "run_id": str(row.run_id) if row.run_id else None,
                "employee_id": str(row.employee_id) if row.employee_id else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    async def get_pref(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
        pref = await self._repo.get_pref(tenant_id, user_id)
        return {
            "user_id": str(pref.user_id),
            "in_app_on": pref.in_app_on,
            "email_on": pref.email_on,
        }

    async def upsert_pref(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        in_app_on: bool,
        email_on: bool,
    ) -> dict[str, Any]:
        pref = await self._repo.upsert_pref(
            tenant_id=tenant_id,
            user_id=user_id,
            in_app_on=in_app_on,
            email_on=email_on,
        )
        await self.commit()
        return {
            "user_id": str(pref.user_id),
            "in_app_on": pref.in_app_on,
            "email_on": pref.email_on,
        }

    async def commit(self) -> None:
        session = getattr(self._repo, "session", None)
        if session is not None:
            await session.commit()

    async def rollback(self) -> None:
        session = getattr(self._repo, "session", None)
        if session is not None:
            await session.rollback()


__all__ = ["PayrollNotificationOrchestrator", "PayrollNotificationRepositoryPort"]
