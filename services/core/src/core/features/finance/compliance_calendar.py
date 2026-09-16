"""Finance compliance calendar (FIN-AUT-004, SKY-85 B27).

Thin service + router for recurring compliance obligations. Open items with
``due_on <= today + lead_days`` drive the reminder list and, later, the
notification-center emission (dedupe key ``compliance:{obligation_id}:{due_on}``).
Completing a recurring item advances ``due_on`` by its recurrence; completing a
one-off closes it. Overdue is derived (``open AND due_on < today``), never stored.

Reads use ``erp.compliance.read``; every write uses ``erp.compliance.write``.
"""

from __future__ import annotations

import calendar
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.api.deps import (
    get_finance_compliance_service,
    require_permission,
)
from core.core.audit_events import (
    FINANCE_COMPLIANCE_ITEM_COMPLETED,
    FINANCE_COMPLIANCE_ITEM_CREATED,
    FINANCE_COMPLIANCE_ITEM_UPDATED,
)
from core.core.logging import get_logger
from core.core.permissions import ERP_COMPLIANCE_READ
from core.db.session import get_db
from core.domain.entities import ComplianceItem
from core.domain.value_objects import ComplianceItemStatus, ComplianceRecurrence
from core.features.finance.ports import AuditSink, FinanceWave4RepositoryPort
from core.features.finance.schemas_wave5 import (
    ComplianceItemRequest,
    ComplianceItemResponse,
    ComplianceItemUpdateRequest,
)
from skyrict_common.exceptions import NotFoundError, ValidationError
from skyrict_common.schemas import ResponseEnvelope

logger = get_logger("core.finance.compliance")

router = APIRouter(prefix="/finance/compliance", tags=["finance-compliance"])

require_compliance_read = require_permission("erp.compliance.read")
require_compliance_write = require_permission("erp.compliance.write")


async def emit_compliance_reminders(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    items: list[ComplianceItem],
) -> None:
    """Emit compliance-due reminders via the notification center (SKY-93).

    One best-effort notification per open obligation due within its lead
    horizon, routed to holders of ``erp.compliance.read`` through the
    mandatory ``compliance`` category.  The dedupe key
    ``compliance:{obligation_id}:{due_on}`` delivers exactly once per
    occurrence regardless of how often the ``/upcoming`` read is polled.

    Severity is ``HIGH`` for overdue items and ``MEDIUM`` for upcoming ones.
    The mandatory category forces in-app delivery; severity only drives
    ranking and whether the row may later be collapsed into a digest (the
    compliance category is never collapsed regardless of severity).

    A producer failure must never break the read response (B34 precedent).
    """
    if not items:
        return

    from core.features.notifications.domain import (
        NotificationDraft,
        NotificationSeverity,
        RecipientSpec,
    )
    from core.features.notifications.producer import NotificationProducer

    today = date.today()
    producer = NotificationProducer(db)
    for item in items:
        if item.status is not ComplianceItemStatus.OPEN:
            continue
        is_overdue = item.due_on < today
        severity = NotificationSeverity.HIGH if is_overdue else NotificationSeverity.MEDIUM
        status_label = "overdue" if is_overdue else "due"
        title = f"{item.title} is {status_label}"
        body = (
            f"Compliance obligation '{item.title}' is {status_label} on {item.due_on.isoformat()}."
        )
        if item.description:
            body += f" {item.description}"

        draft = NotificationDraft(
            dedupe_key=f"compliance:{item.id}:{item.due_on.isoformat()}",
            event_type="finance.compliance_reminder",
            category="compliance",
            module="compliance",
            severity=severity,
            title=title,
            body=body,
            recipients=RecipientSpec.from_permissions(ERP_COMPLIANCE_READ),
            relevance_key=ERP_COMPLIANCE_READ,
            payload={
                "item_id": str(item.id),
                "due_on": item.due_on.isoformat(),
                "obligation_type": item.obligation_type,
            },
        )
        try:
            await producer.emit(draft)
        except Exception:
            logger.exception(
                "compliance.notification.emit_failed",
                tenant_id=str(tenant_id),
                item_id=str(item.id),
                message="compliance reminder emission failed; response unaffected",
            )


def _tenant_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["tenant_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


def _user_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["user_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


def _add_months(day: date, months: int) -> date:
    month_index = day.year * 12 + (day.month - 1) + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def _advance_due_on(due_on: date, recurrence: ComplianceRecurrence) -> date:
    """Advance the next occurrence by one recurrence step (calendar-aware)."""
    if recurrence is ComplianceRecurrence.MONTHLY:
        return _add_months(due_on, 1)
    if recurrence is ComplianceRecurrence.QUARTERLY:
        return _add_months(due_on, 3)
    if recurrence is ComplianceRecurrence.YEARLY:
        return _add_months(due_on, 12)
    raise ValidationError(f"Unknown recurrence '{recurrence}'")


class FinanceComplianceService:
    """Compliance obligations + reminders (thin over the repo)."""

    def __init__(self, repo: FinanceWave4RepositoryPort, audit: AuditSink) -> None:
        self._repo = repo
        self._audit = audit

    async def create_item(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, body: Any
    ) -> ComplianceItem:
        item = ComplianceItem(
            tenant_id=tenant_id,
            title=str(body.title),
            due_on=body.due_on,
            description=body.description,
            obligation_type=body.obligation_type,
            recurrence=self._validated_recurrence(body.recurrence),
            lead_days=int(body.lead_days or 7),
            created_by=user_id,
        )
        created = await self._repo.create_compliance_item(item)
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_COMPLIANCE_ITEM_CREATED,
            target=f"compliance_item:{created.id}",
            details={"title": created.title, "due_on": created.due_on.isoformat()},
        )
        return created

    async def get_item(self, tenant_id: uuid.UUID, item_id: uuid.UUID) -> ComplianceItem:
        item = await self._repo.get_compliance_item(item_id, tenant_id)
        if item is None:
            raise NotFoundError(f"Compliance item {item_id} not found")
        return item

    async def list_items(self, tenant_id: uuid.UUID, status: str | None) -> list[ComplianceItem]:
        return list(await self._repo.list_compliance_items(tenant_id, status=status))

    async def list_upcoming(self, tenant_id: uuid.UUID, lead_days: int) -> list[ComplianceItem]:
        horizon = date.today() + timedelta(days=lead_days)
        return list(await self._repo.list_compliance_due(tenant_id, horizon))

    async def update_item(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, item_id: uuid.UUID, body: Any
    ) -> ComplianceItem:
        current = await self.get_item(tenant_id, item_id)
        if current.status is not ComplianceItemStatus.OPEN:
            raise ValidationError("Only open items can be edited")
        updated = replace(
            current,
            title=body.title if body.title is not None else current.title,
            due_on=body.due_on if body.due_on is not None else current.due_on,
            description=(body.description if body.description is not None else current.description),
            obligation_type=(
                body.obligation_type
                if body.obligation_type is not None
                else current.obligation_type
            ),
            recurrence=(
                self._validated_recurrence(body.recurrence)
                if body.recurrence is not None
                else current.recurrence
            ),
            lead_days=body.lead_days if body.lead_days is not None else current.lead_days,
        )
        if updated.recurrence is not None:
            updated = replace(
                updated, due_on=self._advance_until_future(updated.due_on, updated.recurrence)
            )
        result = await self._repo.update_compliance_item(updated)
        if result is None:
            raise NotFoundError(f"Compliance item {item_id} not found")
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_COMPLIANCE_ITEM_UPDATED,
            target=f"compliance_item:{item_id}",
            details={"title": result.title, "due_on": result.due_on.isoformat()},
        )
        return result

    async def complete(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, item_id: uuid.UUID
    ) -> ComplianceItem:
        current = await self.get_item(tenant_id, item_id)
        now = datetime.now(UTC)
        if current.recurrence is not None:
            next_due = self._advance_until_future(current.due_on, current.recurrence)
            reopened = replace(
                current,
                due_on=next_due,
                status=ComplianceItemStatus.OPEN,
                completed_at=None,
                completed_by=None,
            )
            result = await self._repo.update_compliance_item(reopened)
        else:
            result = await self._repo.complete_compliance_item(
                item_id,
                tenant_id,
                completed_by=user_id,
                completed_at=now,
            )
        if result is None:
            raise NotFoundError(f"Compliance item {item_id} not found")
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_COMPLIANCE_ITEM_COMPLETED,
            target=f"compliance_item:{item_id}",
            details={"next_due_on": result.due_on.isoformat()},
        )
        return result

    def _advance_until_future(self, due_on: date, recurrence: ComplianceRecurrence) -> date:
        while due_on <= date.today():
            due_on = _advance_due_on(due_on, recurrence)
        return due_on

    def _validated_recurrence(self, raw: Any) -> ComplianceRecurrence | None:
        if raw is None:
            return None
        try:
            return ComplianceRecurrence(str(raw))
        except ValueError as exc:
            raise ValidationError(
                f"Invalid recurrence '{raw}' - expected monthly, quarterly, yearly, or null"
            ) from exc


@router.post("", response_model=ResponseEnvelope[ComplianceItemResponse])
async def create_compliance_item(
    body: ComplianceItemRequest,
    current_user: dict[str, Any] = Depends(require_compliance_write),
    svc: FinanceComplianceService = Depends(get_finance_compliance_service),
) -> ResponseEnvelope[ComplianceItemResponse]:
    item = await svc.create_item(_tenant_id(current_user), _user_id(current_user), body)
    return ResponseEnvelope(data=ComplianceItemResponse.model_validate(item))


@router.get("", response_model=ResponseEnvelope[list[ComplianceItemResponse]])
async def list_compliance_items(
    status: str | None = Query(default=None),
    current_user: dict[str, Any] = Depends(require_compliance_read),
    svc: FinanceComplianceService = Depends(get_finance_compliance_service),
) -> ResponseEnvelope[list[ComplianceItemResponse]]:
    today = date.today()
    data = []
    for item in await svc.list_items(_tenant_id(current_user), status):
        response = ComplianceItemResponse.model_validate(item)
        response.overdue = item.status is ComplianceItemStatus.OPEN and item.due_on < today
        data.append(response)
    return ResponseEnvelope(data=data)


@router.get("/upcoming", response_model=ResponseEnvelope[list[ComplianceItemResponse]])
async def list_upcoming_compliance(
    lead_days: int = Query(default=7, ge=0, le=365),
    current_user: dict[str, Any] = Depends(require_compliance_read),
    svc: FinanceComplianceService = Depends(get_finance_compliance_service),
    db: AsyncSession = Depends(get_db),
) -> ResponseEnvelope[list[ComplianceItemResponse]]:
    items = await svc.list_upcoming(_tenant_id(current_user), lead_days)
    await emit_compliance_reminders(
        db,
        tenant_id=_tenant_id(current_user),
        items=items,
    )
    return ResponseEnvelope(data=[ComplianceItemResponse.model_validate(item) for item in items])


@router.get("/{item_id}", response_model=ResponseEnvelope[ComplianceItemResponse])
async def get_compliance_item(
    item_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_compliance_read),
    svc: FinanceComplianceService = Depends(get_finance_compliance_service),
) -> ResponseEnvelope[ComplianceItemResponse]:
    item = await svc.get_item(_tenant_id(current_user), item_id)
    response = ComplianceItemResponse.model_validate(item)
    response.overdue = item.status is ComplianceItemStatus.OPEN and item.due_on < date.today()
    return ResponseEnvelope(data=response)


@router.put("/{item_id}", response_model=ResponseEnvelope[ComplianceItemResponse])
async def update_compliance_item(
    item_id: uuid.UUID,
    body: ComplianceItemUpdateRequest,
    current_user: dict[str, Any] = Depends(require_compliance_write),
    svc: FinanceComplianceService = Depends(get_finance_compliance_service),
) -> ResponseEnvelope[ComplianceItemResponse]:
    item = await svc.update_item(_tenant_id(current_user), _user_id(current_user), item_id, body)
    return ResponseEnvelope(data=ComplianceItemResponse.model_validate(item))


@router.post("/{item_id}/complete", response_model=ResponseEnvelope[ComplianceItemResponse])
async def complete_compliance_item(
    item_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_compliance_write),
    svc: FinanceComplianceService = Depends(get_finance_compliance_service),
) -> ResponseEnvelope[ComplianceItemResponse]:
    item = await svc.complete(_tenant_id(current_user), _user_id(current_user), item_id)
    return ResponseEnvelope(data=ComplianceItemResponse.model_validate(item))
