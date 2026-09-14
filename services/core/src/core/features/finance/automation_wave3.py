"""Finance automation wave 3 - recurring journal templates (FIN-AUT-003 B5).

A thin service + router for template CRUD and generation. Each fire creates a
DRAFT journal entry stamped ``source='journal_template'`` with
``source_ref=f"{template_id}:{entry_date}"`` so the existing
``UNIQUE (tenant_id, source, source_ref)`` lock on journal entries makes every
scheduled occurrence exactly-once (a replayed run-due returns ``created=False``
instead of ever double-booking). Generated drafts ride the normal approval path.

There is no scheduler infra: run-due scans ``enabled AND next_run_at <= now``
and advances each template's ``next_run_at`` with the payroll cron matcher.
Reads use ``erp.finance.read``; all writes (including generate, which only
creates drafts) use ``erp.finance.write``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query

from core.api.deps import get_finance_wave3_service, require_permission
from core.core.audit_events import (
    FINANCE_JOURNAL_TEMPLATE_CREATED,
    FINANCE_JOURNAL_TEMPLATE_DELETED,
    FINANCE_JOURNAL_TEMPLATE_GENERATED,
    FINANCE_JOURNAL_TEMPLATE_UPDATED,
)
from core.core.constants import JOURNAL_SOURCE_TEMPLATE
from core.domain.entities import (
    JournalEntry,
    JournalLine,
    JournalTemplate,
    JournalTemplateLine,
)
from core.domain.value_objects import EntryStatus
from core.features.finance.ports import (
    AuditSink,
    FinanceRepositoryPort,
    JournalTemplateRepositoryPort,
)
from core.features.finance.schemas_wave3 import (
    JournalTemplateCreateRequest,
    JournalTemplateFailureResponse,
    JournalTemplateGeneratedResponse,
    JournalTemplateResponse,
    JournalTemplateRunDueResponse,
    JournalTemplateUpdateRequest,
)
from core.features.payroll_automation.cron import parse_cron
from skyrict_common.exceptions import ConflictError, NotFoundError, ValidationError
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/finance/automation/wave3", tags=["finance-automation-wave3"])

require_finance_read = require_permission("erp.finance.read")
require_finance_write = require_permission("erp.finance.write")


def _tenant_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["tenant_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


def _user_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["user_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


@dataclass
class FinanceWave3Service:
    """Business rules for recurring journal templates (thin over the repo)."""

    repo: JournalTemplateRepositoryPort
    entries: FinanceRepositoryPort
    audit: AuditSink

    def _validated_lines(
        self, raw_lines: list[Any]
    ) -> tuple[JournalTemplateLine, ...]:
        lines: list[JournalTemplateLine] = []
        debit_total = 0.0
        credit_total = 0.0
        for raw in raw_lines:
            debit = getattr(raw, "debit", None)
            credit = getattr(raw, "credit", None)
            if (debit is None) == (credit is None):
                raise ValidationError(
                    f"Line '{raw.account_code}' must set exactly one of debit or credit"
                )
            metadata = getattr(raw, "account_code", None)
            if metadata is None:
                raise ValidationError("Template line missing account_code")
            line = JournalTemplateLine(
                account_code=metadata,
                debit=debit,
                credit=credit,
                currency=getattr(raw, "currency", "USD"),
            )
            lines.append(line)
            debit_total += float(debit or 0)
            credit_total += float(credit or 0)
        if not lines:
            raise ValidationError("Template must have at least two lines")
        if abs(debit_total - credit_total) > 1e-6:
            raise ValidationError(
                f"Template does not balance: debits {debit_total} != credits {credit_total}"
            )
        return tuple(lines)

    def _next_run_at(self, cron_expression: str, base: datetime) -> datetime:
        try:
            return parse_cron(cron_expression).next_match_after(base)
        except ValueError as exc:
            raise ValidationError(f"Invalid cron expression: {exc}") from exc

    def _render_memo(self, template: JournalTemplate, entry_date: date) -> str | None:
        if not template.memo:
            return None
        return template.memo.replace("{date}", entry_date.isoformat())

    async def create_template(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, body: Any
    ) -> JournalTemplate:
        now = datetime.now(UTC)
        lines = self._validated_lines(body.lines)
        template = JournalTemplate(
            tenant_id=tenant_id,
            name=str(body.name),
            description=body.description,
            cron_expression=str(body.cron_expression),
            entry_date_offset_days=int(body.entry_date_offset_days or 0),
            memo=body.memo,
            lines=lines,
            next_run_at=self._next_run_at(str(body.cron_expression), now),
        )
        created = await self.repo.create_journal_template(template)
        await self.audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_JOURNAL_TEMPLATE_CREATED,
            target=f"journal_template:{created.id}",
            details={"name": created.name, "cron": created.cron_expression},
        )
        return created

    async def get_template(
        self, tenant_id: uuid.UUID, template_id: uuid.UUID
    ) -> JournalTemplate:
        template = await self.repo.get_journal_template(template_id, tenant_id)
        if template is None:
            raise NotFoundError(f"Journal template {template_id} not found")
        return template

    async def list_templates(
        self, tenant_id: uuid.UUID, enabled: bool | None
    ) -> list[JournalTemplate]:
        return list(await self.repo.list_journal_templates(tenant_id, enabled=enabled))

    async def update_template(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, template_id: uuid.UUID, body: Any
    ) -> JournalTemplate:
        current = await self.get_template(tenant_id, template_id)
        cron = body.cron_expression if body.cron_expression is not None else current.cron_expression
        lines = (
            self._validated_lines(body.lines)
            if body.lines is not None
            else current.lines
        )
        updated = replace(
            current,
            name=body.name if body.name is not None else current.name,
            description=body.description if body.description is not None else current.description,
            cron_expression=cron,
            entry_date_offset_days=(
                body.entry_date_offset_days
                if body.entry_date_offset_days is not None
                else current.entry_date_offset_days
            ),
            memo=body.memo if body.memo is not None else current.memo,
            enabled=body.enabled if body.enabled is not None else current.enabled,
            lines=lines,
            next_run_at=self._next_run_at(cron, datetime.now(UTC)),
        )
        result = await self.repo.update_journal_template(updated)
        if result is None:
            raise NotFoundError(f"Journal template {template_id} not found")
        await self.audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_JOURNAL_TEMPLATE_UPDATED,
            target=f"journal_template:{result.id}",
            details={"name": result.name, "cron": result.cron_expression},
        )
        return result

    async def delete_template(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, template_id: uuid.UUID
    ) -> None:
        deleted = await self.repo.delete_journal_template(template_id, tenant_id)
        if not deleted:
            raise NotFoundError(f"Journal template {template_id} not found")
        await self.audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_JOURNAL_TEMPLATE_DELETED,
            target=f"journal_template:{template_id}",
        )

    async def generate(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        template_id: uuid.UUID,
        fire_at: datetime,
    ) -> JournalTemplateGeneratedResponse:
        template = await self.get_template(tenant_id, template_id)
        entry_date = fire_at.date() + timedelta(days=template.entry_date_offset_days)
        memo = self._render_memo(template, entry_date)
        source_ref = f"{template_id}:{entry_date.isoformat()}"
        lines: list[JournalLine] = []
        for raw in template.lines:
            account = await self.entries.get_account_by_code(raw.account_code, tenant_id)
            if account is None or account.id is None:
                raise ValidationError(
                    f"Template '{template.name}' references unknown account code "
                    f"'{raw.account_code}' - fix the template"
                )
            lines.append(
                JournalLine(
                    account_id=account.id,
                    debit=raw.debit,
                    credit=raw.credit,
                    currency=raw.currency,
                )
            )
        entry = JournalEntry(
            tenant_id=tenant_id,
            entry_date=entry_date,
            memo=memo,
            status=EntryStatus.DRAFT,
            source=JOURNAL_SOURCE_TEMPLATE,
            source_ref=source_ref,
            lines=tuple(lines),
        )
        try:
            created_entry = await self.entries.create_journal_entry(entry)
        except ConflictError:
            # Exactly-once: this occurrence already fired. Advance the schedule
            # anyway so a fresh scan does not loop on the same occurrence.
            await self._advance(template, fire_at)
            return JournalTemplateGeneratedResponse(
                template_id=template_id,
                template_name=template.name,
                entry_date=entry_date,
                memo=memo,
                created=False,
            )
        await self.audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_JOURNAL_TEMPLATE_GENERATED,
            target=f"journal_template:{template_id}",
            details={
                "entry_id": str(created_entry.id),
                "entry_date": entry_date.isoformat(),
                "memo": memo,
            },
        )
        await self._advance(template, fire_at)
        return JournalTemplateGeneratedResponse(
            template_id=template_id,
            template_name=template.name,
            entry_date=entry_date,
            entry_id=created_entry.id,
            memo=memo,
            created=True,
        )

    async def _advance(self, template: JournalTemplate, fire_at: datetime) -> None:
        next_run = self._next_run_at(template.cron_expression, fire_at)
        updated = replace(
            template,
            last_fired_at=datetime.now(UTC),
            next_run_at=next_run,
        )
        await self.repo.update_journal_template(updated)

    async def run_due(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, at: datetime
    ) -> JournalTemplateRunDueResponse:
        due = await self.repo.list_journal_templates_due(tenant_id, at)
        generated: list[JournalTemplateGeneratedResponse] = []
        failed: list[JournalTemplateFailureResponse] = []
        for template in due:
            if template.id is None:
                continue  # unreachable: the repo assigns an id on insert
            try:
                result = await self.generate(tenant_id, user_id, template.id, at)
            except (NotFoundError, ValidationError) as exc:
                failed.append(
                    JournalTemplateFailureResponse(
                        template_id=template.id,
                        template_name=template.name,
                        reason=str(exc),
                    )
                )
                continue
            generated.append(result)
        return JournalTemplateRunDueResponse(
            ran_at=at,
            total_due=len(due),
            generated=generated,
            failed=failed,
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/templates", response_model=ResponseEnvelope[JournalTemplateResponse])
async def create_journal_template(
    body: JournalTemplateCreateRequest,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: FinanceWave3Service = Depends(get_finance_wave3_service),
) -> ResponseEnvelope[JournalTemplateResponse]:
    template = await svc.create_template(
        _tenant_id(current_user), _user_id(current_user), body
    )
    return ResponseEnvelope(data=JournalTemplateResponse.model_validate(template))


@router.get("/templates", response_model=ResponseEnvelope[list[JournalTemplateResponse]])
async def list_journal_templates(
    enabled: bool | None = Query(default=None),
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceWave3Service = Depends(get_finance_wave3_service),
) -> ResponseEnvelope[list[JournalTemplateResponse]]:
    templates = await svc.list_templates(_tenant_id(current_user), enabled)
    return ResponseEnvelope(
        data=[JournalTemplateResponse.model_validate(t) for t in templates]
    )


# Registered before /templates/{template_id}-routes so 'due' is never captured
# as a template id.
@router.post(
    "/templates/due/generate",
    response_model=ResponseEnvelope[JournalTemplateRunDueResponse],
)
async def run_due_templates(
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: FinanceWave3Service = Depends(get_finance_wave3_service),
) -> ResponseEnvelope[JournalTemplateRunDueResponse]:
    result = await svc.run_due(_tenant_id(current_user), _user_id(current_user), datetime.now(UTC))
    return ResponseEnvelope(data=result)


@router.get(
    "/templates/{template_id}", response_model=ResponseEnvelope[JournalTemplateResponse]
)
async def get_journal_template(
    template_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceWave3Service = Depends(get_finance_wave3_service),
) -> ResponseEnvelope[JournalTemplateResponse]:
    template = await svc.get_template(_tenant_id(current_user), template_id)
    return ResponseEnvelope(data=JournalTemplateResponse.model_validate(template))


@router.put(
    "/templates/{template_id}", response_model=ResponseEnvelope[JournalTemplateResponse]
)
async def update_journal_template(
    template_id: uuid.UUID,
    body: JournalTemplateUpdateRequest,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: FinanceWave3Service = Depends(get_finance_wave3_service),
) -> ResponseEnvelope[JournalTemplateResponse]:
    template = await svc.update_template(
        _tenant_id(current_user), _user_id(current_user), template_id, body
    )
    return ResponseEnvelope(data=JournalTemplateResponse.model_validate(template))


@router.post(
    "/templates/{template_id}/generate",
    response_model=ResponseEnvelope[JournalTemplateGeneratedResponse],
)
async def generate_journal_template(
    template_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: FinanceWave3Service = Depends(get_finance_wave3_service),
) -> ResponseEnvelope[JournalTemplateGeneratedResponse]:
    result = await svc.generate(
        _tenant_id(current_user),
        _user_id(current_user),
        template_id,
        datetime.now(UTC),
    )
    return ResponseEnvelope(data=result)


@router.delete(
    "/templates/{template_id}", response_model=ResponseEnvelope[dict[str, bool]]
)
async def delete_journal_template(
    template_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: FinanceWave3Service = Depends(get_finance_wave3_service),
) -> ResponseEnvelope[dict[str, bool]]:
    await svc.delete_template(_tenant_id(current_user), _user_id(current_user), template_id)
    return ResponseEnvelope(data={"deleted": True})
