"""Postgres persistence for payroll notifications + delivery preferences.

Covers the post-commit orchestrator's reads (done items, employee → user
resolution, delivery preferences, payroll-admin user ids) and writes
(dedupe-keyed notification inserts — ``ON CONFLICT DO NOTHING`` so the
acceptance criterion "each employee holds exactly one notification row" holds
under re-invocation), plus the preference rows whose absence means the
defaults (in-app ON, email OFF).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.core.permissions import ERP_PAYROLL_AI_READ
from core.features.hr.models.employee import (
    EmployeeModel as HrEmployeeModel,
)
from core.features.payroll_automation.constants import (
    DEFAULT_EMAIL_ON,
    DEFAULT_IN_APP_ON,
    ITEM_DONE,
    ITEM_FAILED,
)
from core.features.payroll_automation.domain import (
    PayrollNotification,
    PayrollNotificationPref,
)
from core.features.payroll_automation.models import (
    PayrollBatchItemModel,
    PayrollNotificationModel,
    PayrollNotificationPrefModel,
)
from core.models.core_role import CoreRoleModel
from core.models.core_user_role import CoreUserRoleModel

NotificationModel = PayrollNotificationModel
PrefModel = PayrollNotificationPrefModel


def _to_notification(row: PayrollNotificationModel) -> PayrollNotification:
    return PayrollNotification(
        tenant_id=row.tenant_id,
        recipient_user_id=row.recipient_user_id,
        event_type=row.event_type,
        dedupe_key=row.dedupe_key,
        in_app=row.in_app,
        email_stub=row.email_stub,
        subject=row.subject,
        body=row.body,
        batch_id=row.batch_id,
        run_id=row.run_id,
        employee_id=row.employee_id,
        id=row.id,
        created_at=row.created_at,
    )


class PostgresPayrollNotificationRepository:
    """``ai_payroll_notifications`` + ``ai_payroll_notification_prefs`` access."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    # --- Orchestrator inputs --------------------------------------------------

    async def done_employee_ids(
        self, batch_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """Employee ids whose batch item completed (got a committed entry)."""
        rows = (
            (
                await self._session.execute(
                    sa.select(PayrollBatchItemModel.employee_id)
                    .where(
                        PayrollBatchItemModel.tenant_id == tenant_id,
                        PayrollBatchItemModel.batch_id == batch_id,
                        PayrollBatchItemModel.status == ITEM_DONE,
                    )
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        return [uuid.UUID(str(item_id)) for item_id in rows]

    async def employee_user_ids(
        self,
        tenant_id: uuid.UUID,
        employee_ids: Sequence[uuid.UUID],
    ) -> dict[uuid.UUID, uuid.UUID | None]:
        """Map an employee id to its linked identity user (None when unlinked)."""
        if not employee_ids:
            return {}
        rows = (
            await self._session.execute(
                sa.select(HrEmployeeModel.id, HrEmployeeModel.user_id).where(
                    HrEmployeeModel.tenant_id == tenant_id,
                    HrEmployeeModel.id.in_(employee_ids),
                )
            )
        ).all()
        mapped = {row.id: row.user_id for row in rows}
        return {employee_id: mapped.get(employee_id) for employee_id in employee_ids}

    async def failed_item_errors(
        self, batch_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> list[dict[str, str]]:
        """Employee id + error text for every failed batch item."""
        rows = (
            await self._session.execute(
                sa.select(
                    PayrollBatchItemModel.employee_id,
                    PayrollBatchItemModel.error_text,
                )
                .where(
                    PayrollBatchItemModel.tenant_id == tenant_id,
                    PayrollBatchItemModel.batch_id == batch_id,
                    PayrollBatchItemModel.status == ITEM_FAILED,
                )
                .order_by(PayrollBatchItemModel.employee_id)
            )
        ).all()
        return [
            {"employee_id": str(row.employee_id), "error_text": row.error_text or ""}
            for row in rows
        ]

    async def user_ids_with_permission(
        self,
        tenant_id: uuid.UUID,
        *,
        permission: str = ERP_PAYROLL_AI_READ,
    ) -> list[uuid.UUID]:
        """Users granted a permission in this tenant via any role."""
        rows = (
            (
                await self._session.execute(
                    sa.select(CoreUserRoleModel.user_id)
                    .join(
                        CoreRoleModel,
                        sa.and_(
                            CoreRoleModel.tenant_id == CoreUserRoleModel.tenant_id,
                            CoreRoleModel.id == CoreUserRoleModel.role_id,
                        ),
                    )
                    .where(
                        CoreUserRoleModel.tenant_id == tenant_id,
                        CoreRoleModel.permissions.any(permission),  # type: ignore[arg-type]
                    )
                    .order_by(CoreUserRoleModel.user_id)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        return [uuid.UUID(str(user_id)) for user_id in rows]

    # --- Preferences ----------------------------------------------------------

    async def get_pref(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> PayrollNotificationPref:
        """Merged preference for one user — defaults when no row exists."""
        row = (
            await self._session.execute(
                sa.select(PrefModel).where(
                    PrefModel.tenant_id == tenant_id,
                    PrefModel.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return PayrollNotificationPref(
                tenant_id=row.tenant_id,
                user_id=row.user_id,
                in_app_on=row.in_app_on,
                email_on=row.email_on,
            )
        return PayrollNotificationPref(
            tenant_id=tenant_id,
            user_id=user_id,
            in_app_on=DEFAULT_IN_APP_ON,
            email_on=DEFAULT_EMAIL_ON,
        )

    async def prefs_for_users(
        self,
        tenant_id: uuid.UUID,
        user_ids: Sequence[uuid.UUID],
    ) -> dict[uuid.UUID, PayrollNotificationPref]:
        """Bulk merged preferences — missing rows resolve to the defaults."""
        merged = {
            user_id: PayrollNotificationPref(
                tenant_id=tenant_id,
                user_id=user_id,
                in_app_on=DEFAULT_IN_APP_ON,
                email_on=DEFAULT_EMAIL_ON,
            )
            for user_id in user_ids
        }
        if not user_ids:
            return merged
        rows = (
            (
                await self._session.execute(
                    sa.select(PrefModel).where(
                        PrefModel.tenant_id == tenant_id,
                        PrefModel.user_id.in_(user_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            merged[row.user_id] = PayrollNotificationPref(
                tenant_id=row.tenant_id,
                user_id=row.user_id,
                in_app_on=row.in_app_on,
                email_on=row.email_on,
            )
        return merged

    async def upsert_pref(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        in_app_on: bool,
        email_on: bool,
    ) -> PayrollNotificationPref:
        stmt = pg_insert(PrefModel).values(
            tenant_id=tenant_id,
            user_id=user_id,
            in_app_on=in_app_on,
            email_on=email_on,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="ai_payroll_notification_prefs_pkey",
            set_={
                "in_app_on": in_app_on,
                "email_on": email_on,
            },
        )
        await self._session.execute(stmt)
        await self._session.flush()
        return PayrollNotificationPref(
            tenant_id=tenant_id,
            user_id=user_id,
            in_app_on=in_app_on,
            email_on=email_on,
        )

    # --- Notifications --------------------------------------------------------

    async def insert_notifications(
        self,
        *,
        tenant_id: uuid.UUID,
        notifications: Sequence[PayrollNotification],
    ) -> int:
        """Insert notification rows, ignoring any that violate the dedupe key.

        Returns the number actually inserted (dedupe tells the caller whether a
        recipient already holds the event, driving the "exactly one row"
        criterion under re-invocation).
        """
        if not notifications:
            return 0
        rows = [
            {
                "tenant_id": tenant_id,
                "recipient_user_id": n.recipient_user_id,
                "event_type": n.event_type,
                "dedupe_key": n.dedupe_key,
                "in_app": n.in_app,
                "email_stub": n.email_stub,
                "subject": n.subject,
                "body": n.body,
                "batch_id": n.batch_id,
                "run_id": n.run_id,
                "employee_id": n.employee_id,
            }
            for n in notifications
        ]
        stmt = (
            pg_insert(NotificationModel)
            .values(rows)
            .on_conflict_do_nothing(
                constraint="uq_ai_payroll_notifications_dedupe",
            )
        )
        result = await self._session.execute(stmt)
        return int(result.rowcount)  # type: ignore[attr-defined]  # DML returns CursorResult

    async def list_notifications(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID | None = None,
        event_type: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[PayrollNotification]:
        stmt = sa.select(NotificationModel).where(NotificationModel.tenant_id == tenant_id)
        if recipient_user_id is not None:
            stmt = stmt.where(NotificationModel.recipient_user_id == recipient_user_id)
        if event_type is not None:
            stmt = stmt.where(NotificationModel.event_type == event_type)
        if after is not None:
            stmt = stmt.where(NotificationModel.created_at >= after)
        if before is not None:
            stmt = stmt.where(NotificationModel.created_at < before)
        stmt = stmt.order_by(NotificationModel.created_at.desc(), NotificationModel.id).limit(limit)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_notification(row) for row in rows]


__all__ = ["PostgresPayrollNotificationRepository"]
