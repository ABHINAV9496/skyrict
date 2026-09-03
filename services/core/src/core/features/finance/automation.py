"""Finance automation routes — SKY-56/SKY-64 wave 1.

A thin service + router over :class:`FinanceRepositoryPort` for the finance
automation widgets: close checklist, duplicates, account-code suggestions,
working-capital alert, health score, cash-flow projection, anomalies,
comparative P&L, journal-entry reversal, and tenant automation settings.

Reads use ``erp.finance.read``; the reversal (a money moment) uses
``erp.finance.approve``; settings writes use ``erp.finance.write``.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends

from core.api.deps import (
    get_finance_automation_service,
    get_finance_automation_service_with_ai,
    require_permission,
)
from core.core.audit_events import (
    FINANCE_AI_ANOMALY_NARRATED,
    FINANCE_AI_DRAFT_GENERATED,
    FINANCE_AI_REMINDER_GENERATED,
    FINANCE_ANOMALY_DETECTED,
    FINANCE_DUPLICATE_SUGGESTION_CREATED,
    FINANCE_JOURNAL_ENTRY_REVERSED,
)
from core.core.exceptions import AiServiceUnavailableError
from core.domain.entities import (
    AccountCodeSuggestion,
    AiFinanceAnomaly,
    AiFinanceSuggestion,
    ChartOfAccount,
    DraftEntry,
    DraftEntryLine,
    ReminderDraft,
)
from core.features.finance.ports import AuditSink, FinanceRepositoryPort
from core.features.finance.schemas import (
    AccountCodeSuggestionResponse,
    AnomalyNarrationResponse,
    AnomalyResponse,
    ArAgingResponse,
    CashflowProjectionResponse,
    CloseChecklistResponse,
    ComparativePnlResponse,
    DraftEntryLineResponse,
    DraftEntryResponse,
    DuplicateGroupResponse,
    HealthScoreResponse,
    JournalEntryResponse,
    ReminderDraftLineResponse,
    ReminderDraftResponse,
    ReminderGenerateRequest,
    SuggestAccountCodeRequest,
    TenantSettingsResponse,
    WorkingCapitalAlertResponse,
    WorkingCapitalSettingsRequest,
)
from skyrict_common.exceptions import NotFoundError
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/finance/automation", tags=["finance-automation"])

require_finance_read = require_permission("erp.finance.read")
require_finance_write = require_permission("erp.finance.write")
require_finance_approve = require_permission("erp.finance.approve")
require_finance_ai_read = require_permission("erp.finance.ai.read")
require_finance_ai_write = require_permission("erp.finance.ai.write")


def _tenant_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["tenant_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


def _user_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["user_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


AiSuggester = Callable[[str, Sequence[ChartOfAccount]], Awaitable[AccountCodeSuggestion | None]]
AiDrafter = Callable[[str, Sequence[ChartOfAccount]], Awaitable[DraftEntry | None]]


@dataclass
class FinanceAutomationService:
    """Business rules for finance automation widgets (thin over the repo)."""

    repo: FinanceRepositoryPort
    audit: AuditSink
    ai_suggest: AiSuggester | None = field(default=None)
    ai_draft: AiDrafter | None = field(default=None)

    async def close_checklist(self, tenant_id: uuid.UUID, period_id: uuid.UUID) -> Any:
        return await self.repo.close_checklist(tenant_id, period_id)

    async def duplicates(self, tenant_id: uuid.UUID) -> Any:
        return await self.repo.duplicates(tenant_id)

    async def suggest_account_code(self, tenant_id: uuid.UUID, description: str) -> Any:
        accounts = await self.repo.list_accounts(tenant_id)
        suggestion: AccountCodeSuggestion
        if self.ai_suggest is not None and accounts:
            try:
                ai = await self.ai_suggest(description, accounts)
            except AiServiceUnavailableError:
                ai = None
            suggestion = ai or await self.repo.suggest_account_code(tenant_id, description)
        else:
            suggestion = await self.repo.suggest_account_code(tenant_id, description)
        if suggestion.suggested_code:
            await self.repo.upsert_ai_suggestion(
                tenant_id,
                AiFinanceSuggestion(
                    tenant_id=tenant_id,
                    description=description,
                    suggested_code=suggestion.suggested_code,
                    suggested_name=suggestion.suggested_name,
                    confidence=suggestion.confidence,
                ),
            )
            await self.audit.log(
                tenant_id=tenant_id,
                user_id=None,
                action=FINANCE_DUPLICATE_SUGGESTION_CREATED,
                target="finance:suggestion",
                details={"code": suggestion.suggested_code},
            )
        return suggestion

    async def working_capital_alert(self, tenant_id: uuid.UUID, as_of: date) -> Any:
        return await self.repo.working_capital_alert(tenant_id, as_of)

    async def health_score(self, tenant_id: uuid.UUID, as_of: date) -> Any:
        return await self.repo.health_score(tenant_id, as_of)

    async def cashflow_projection(self, tenant_id: uuid.UUID, as_of: date) -> Any:
        return await self.repo.cashflow_projection(tenant_id, as_of)

    async def run_anomaly_scan(self, tenant_id: uuid.UUID) -> Any:
        detected: list[AiFinanceAnomaly] = []
        dupes = await self.repo.duplicates(tenant_id)
        for group in dupes:
            first = group.entries[0]
            anomaly = await self.repo.upsert_ai_anomaly(
                tenant_id,
                AiFinanceAnomaly(
                    tenant_id=tenant_id,
                    entity_type="journal_entry",
                    entity_id=first.entry_id,
                    anomaly_type="duplicate_entry",
                    severity="medium",
                    description=group.reason,
                ),
            )
            detected.append(anomaly)
        for anomaly in detected:
            await self.audit.log(
                tenant_id=tenant_id,
                user_id=None,
                action=FINANCE_ANOMALY_DETECTED,
                target=f"journal_entry:{anomaly.entity_id}",
                details={"anomaly_type": anomaly.anomaly_type},
            )
        return detected

    async def anomalies(self, tenant_id: uuid.UUID) -> Any:
        return await self.repo.list_open_ai_anomalies(tenant_id)

    async def comparative_pnl(
        self,
        tenant_id: uuid.UUID,
        current_from: date,
        current_to: date,
        prior_from: date,
        prior_to: date,
    ) -> Any:
        return await self.repo.comparative_pnl(
            tenant_id, current_from, current_to, prior_from, prior_to
        )

    async def reverse_journal_entry(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, entry_id: uuid.UUID
    ) -> Any:
        entry = await self.repo.get_journal_entry(entry_id, tenant_id)
        if entry is None:
            raise NotFoundError(f"Journal entry {entry_id} not found")
        if entry.status.value != "posted":
            raise NotFoundError("Only posted journal entries can be reversed")
        if entry.reversal_entry_id is not None:
            raise NotFoundError("Journal entry has already been reversed")
        reversed_entry = await self.repo.reverse_journal_entry(
            entry_id,
            tenant_id,
            reversed_by_user_id=user_id,
            reversed_at=datetime.now(),
        )
        if reversed_entry is None:
            raise NotFoundError("Journal entry could not be reversed")
        await self.audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_JOURNAL_ENTRY_REVERSED,
            target=f"journal_entry:{entry_id}",
            details={"reversal_entry_id": str(reversed_entry.reversal_entry_id)},
        )
        return reversed_entry

    async def get_settings(self, tenant_id: uuid.UUID) -> TenantSettingsResponse:
        setting = await self.repo.get_tenant_setting(tenant_id, "working_capital_threshold")
        value = setting.value if setting else "1.5"
        return TenantSettingsResponse(working_capital_threshold=Decimal(value))

    async def put_settings(self, tenant_id: uuid.UUID, threshold: Any) -> TenantSettingsResponse:
        await self.repo.upsert_tenant_setting(
            tenant_id, "working_capital_threshold", str(threshold)
        )
        return TenantSettingsResponse(working_capital_threshold=Decimal(str(threshold)))

    async def draft_journal_entry(self, tenant_id: uuid.UUID, description: str) -> DraftEntry:
        accounts = await self.repo.list_accounts(tenant_id)
        if self.ai_draft is not None and accounts:
            try:
                ai = await self.ai_draft(description, accounts)
            except AiServiceUnavailableError:
                ai = None
            if ai is not None:
                await self.audit.log(
                    tenant_id=tenant_id,
                    user_id=None,
                    action=FINANCE_AI_DRAFT_GENERATED,
                    target="finance:draft",
                    details={"description": description, "model_used": ai.model_used},
                )
                return ai
        # Deterministic fallback: suggest debit + contra credit
        suggestion = await self.repo.suggest_account_code(tenant_id, description)
        from decimal import Decimal

        draft = DraftEntry(
            lines=(
                DraftEntryLine(
                    account_code=suggestion.suggested_code,
                    account_name=suggestion.suggested_name,
                    amount=Decimal("0"),
                    side="debit",
                    description=description,
                ),
                DraftEntryLine(
                    account_code=suggestion.contra_code or suggestion.suggested_code,
                    account_name=suggestion.contra_name or "",
                    amount=Decimal("0"),
                    side="credit",
                    description=description,
                ),
            ),
            explanation="",
            confidence=suggestion.confidence,
            reasoning="Deterministic fallback — AI service unavailable",
        )
        await self.audit.log(
            tenant_id=tenant_id,
            user_id=None,
            action=FINANCE_AI_DRAFT_GENERATED,
            target="finance:draft",
            details={"description": description},
        )
        return draft

    async def narrate_anomaly(self, tenant_id: uuid.UUID, anomaly_id: uuid.UUID) -> dict[str, str]:
        anomaly = await self.repo.get_ai_anomaly(tenant_id, anomaly_id)
        if anomaly is None:
            raise NotFoundError(f"Anomaly {anomaly_id} not found")
        # AI narration requires the ai_suggest callable to be wired with
        # the narrate function. This is handled in the deps factory.
        # Fallback: return a basic narration from the description
        narration = {
            "narration": f"Anomaly detected: {anomaly.anomaly_type} — {anomaly.description}",
            "model_used": "",
        }
        await self.audit.log(
            tenant_id=tenant_id,
            user_id=None,
            action=FINANCE_AI_ANOMALY_NARRATED,
            target=f"finance:anomaly:{anomaly_id}",
            details={"anomaly_type": anomaly.anomaly_type},
        )
        return narration

    async def generate_reminder(self, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> ReminderDraft:
        invoice = await self.repo.get_invoice_by_id(tenant_id, invoice_id)
        if invoice is None:
            raise NotFoundError(f"Invoice {invoice_id} not found")
        from datetime import date as _date

        days_overdue = (_date.today() - invoice.due_date).days if invoice.due_date else 0
        tone = "polite" if days_overdue < 30 else "firm" if days_overdue < 60 else "final"
        reminder = ReminderDraft(
            invoice_number=invoice.invoice_number,
            customer_name=None,
            amount=invoice.total,
            days_overdue=days_overdue,
            tone=tone,
            subject=f"Payment Reminder — Invoice {invoice.invoice_number}",
            body=f"Please remit payment for invoice {invoice.invoice_number} totaling {invoice.total}.",
            model_used="",
        )
        await self.audit.log(
            tenant_id=tenant_id,
            user_id=None,
            action=FINANCE_AI_REMINDER_GENERATED,
            target=f"finance:invoice:{invoice_id}",
            details={"invoice": invoice.invoice_number, "tone": tone},
        )
        return reminder

    async def batch_reminders(self, tenant_id: uuid.UUID) -> list[ReminderDraft]:
        invoices = await self.repo.list_invoices_overdue(tenant_id)
        reminders = []
        for inv in invoices:
            from datetime import date as _date

            days_overdue = (_date.today() - inv.due_date).days if inv.due_date else 0
            tone = "polite" if days_overdue < 30 else "firm" if days_overdue < 60 else "final"
            reminders.append(
                ReminderDraft(
                    invoice_number=inv.invoice_number,
                    customer_name=None,
                    amount=inv.total,
                    days_overdue=days_overdue,
                    tone=tone,
                    subject=f"Payment Reminder — Invoice {inv.invoice_number}",
                    body=f"Please remit payment for invoice {inv.invoice_number} totaling {inv.total}.",
                    model_used="",
                )
            )
        return reminders


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/aging", response_model=ResponseEnvelope[ArAgingResponse])
async def get_aging(
    as_of: date,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceAutomationService = Depends(get_finance_automation_service),
) -> ResponseEnvelope[ArAgingResponse]:
    aging = await svc.repo.ar_aging(_tenant_id(current_user), as_of)
    return ResponseEnvelope(data=ArAgingResponse.model_validate(aging))


@router.get("/close-checklist", response_model=ResponseEnvelope[CloseChecklistResponse])
async def get_close_checklist(
    period_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceAutomationService = Depends(get_finance_automation_service),
) -> ResponseEnvelope[CloseChecklistResponse]:
    checklist = await svc.close_checklist(_tenant_id(current_user), period_id)
    return ResponseEnvelope(data=CloseChecklistResponse.model_validate(checklist))


@router.get(
    "/duplicates",
    response_model=ResponseEnvelope[list[DuplicateGroupResponse]],
)
async def get_duplicates(
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceAutomationService = Depends(get_finance_automation_service),
) -> ResponseEnvelope[list[DuplicateGroupResponse]]:
    groups = await svc.duplicates(_tenant_id(current_user))
    return ResponseEnvelope(data=[DuplicateGroupResponse.model_validate(g) for g in groups])


@router.post(
    "/suggest-account-code",
    response_model=ResponseEnvelope[AccountCodeSuggestionResponse],
)
async def suggest_account_code(
    body: SuggestAccountCodeRequest,
    current_user: dict[str, Any] = Depends(require_finance_ai_read),
    svc: FinanceAutomationService = Depends(get_finance_automation_service_with_ai),
) -> ResponseEnvelope[AccountCodeSuggestionResponse]:
    suggestion = await svc.suggest_account_code(_tenant_id(current_user), body.description)
    return ResponseEnvelope(data=AccountCodeSuggestionResponse.model_validate(suggestion))


@router.get(
    "/working-capital-alert",
    response_model=ResponseEnvelope[WorkingCapitalAlertResponse],
)
async def get_working_capital_alert(
    as_of: date,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceAutomationService = Depends(get_finance_automation_service),
) -> ResponseEnvelope[WorkingCapitalAlertResponse]:
    alert = await svc.working_capital_alert(_tenant_id(current_user), as_of)
    return ResponseEnvelope(data=WorkingCapitalAlertResponse.model_validate(alert))


@router.get("/health-score", response_model=ResponseEnvelope[HealthScoreResponse])
async def get_health_score(
    as_of: date,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceAutomationService = Depends(get_finance_automation_service),
) -> ResponseEnvelope[HealthScoreResponse]:
    score = await svc.health_score(_tenant_id(current_user), as_of)
    return ResponseEnvelope(data=HealthScoreResponse.model_validate(score))


@router.get(
    "/cashflow-projection",
    response_model=ResponseEnvelope[CashflowProjectionResponse],
)
async def get_cashflow_projection(
    as_of: date,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceAutomationService = Depends(get_finance_automation_service),
) -> ResponseEnvelope[CashflowProjectionResponse]:
    projection = await svc.cashflow_projection(_tenant_id(current_user), as_of)
    return ResponseEnvelope(data=CashflowProjectionResponse.model_validate(projection))


@router.post("/anomalies/scan", response_model=ResponseEnvelope[list[AnomalyResponse]])
async def scan_anomalies(
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceAutomationService = Depends(get_finance_automation_service),
) -> ResponseEnvelope[list[AnomalyResponse]]:
    anomalies = await svc.run_anomaly_scan(_tenant_id(current_user))
    return ResponseEnvelope(data=[AnomalyResponse.model_validate(a) for a in anomalies])


@router.get("/anomalies", response_model=ResponseEnvelope[list[AnomalyResponse]])
async def list_anomalies(
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceAutomationService = Depends(get_finance_automation_service),
) -> ResponseEnvelope[list[AnomalyResponse]]:
    anomalies = await svc.anomalies(_tenant_id(current_user))
    return ResponseEnvelope(data=[AnomalyResponse.model_validate(a) for a in anomalies])


@router.get("/reports/comparative-pnl", response_model=ResponseEnvelope[ComparativePnlResponse])
async def get_comparative_pnl(
    current_from: date,
    current_to: date,
    prior_from: date,
    prior_to: date,
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceAutomationService = Depends(get_finance_automation_service),
) -> ResponseEnvelope[ComparativePnlResponse]:
    pnl = await svc.comparative_pnl(
        _tenant_id(current_user), current_from, current_to, prior_from, prior_to
    )
    return ResponseEnvelope(data=ComparativePnlResponse.model_validate(pnl))


@router.post(
    "/journal-entries/{entry_id}/reverse",
    response_model=ResponseEnvelope[JournalEntryResponse],
)
async def reverse_journal_entry(
    entry_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_approve),
    svc: FinanceAutomationService = Depends(get_finance_automation_service),
) -> ResponseEnvelope[JournalEntryResponse]:
    entry = await svc.reverse_journal_entry(
        _tenant_id(current_user), _user_id(current_user), entry_id
    )
    return ResponseEnvelope(data=JournalEntryResponse.model_validate(entry))


@router.get("/settings", response_model=ResponseEnvelope[TenantSettingsResponse])
async def get_settings(
    current_user: dict[str, Any] = Depends(require_finance_read),
    svc: FinanceAutomationService = Depends(get_finance_automation_service),
) -> ResponseEnvelope[TenantSettingsResponse]:
    return ResponseEnvelope(data=await svc.get_settings(_tenant_id(current_user)))


@router.put("/settings", response_model=ResponseEnvelope[TenantSettingsResponse])
async def put_settings(
    body: WorkingCapitalSettingsRequest,
    current_user: dict[str, Any] = Depends(require_finance_write),
    svc: FinanceAutomationService = Depends(get_finance_automation_service),
) -> ResponseEnvelope[TenantSettingsResponse]:
    settings = await svc.put_settings(_tenant_id(current_user), body.threshold)
    return ResponseEnvelope(data=settings)


# ---------------------------------------------------------------------------
# AI Draft / Narrate / Remind endpoints (FIN-AI-001)
# ---------------------------------------------------------------------------


@router.post("/draft-entry", response_model=ResponseEnvelope[DraftEntryResponse])
async def draft_journal_entry(
    body: SuggestAccountCodeRequest,
    current_user: dict[str, Any] = Depends(require_finance_ai_read),
    svc: FinanceAutomationService = Depends(get_finance_automation_service_with_ai),
) -> ResponseEnvelope[DraftEntryResponse]:
    draft = await svc.draft_journal_entry(_tenant_id(current_user), body.description)
    return ResponseEnvelope(
        data=DraftEntryResponse(
            lines=[
                DraftEntryLineResponse(
                    account_code=line.account_code,
                    account_name=line.account_name,
                    amount=line.amount,
                    side=line.side,
                    description=line.description,
                )
                for line in draft.lines
            ],
            explanation=draft.explanation,
            confidence=draft.confidence,
            reasoning=draft.reasoning,
            model_used=draft.model_used,
        )
    )


@router.post(
    "/anomalies/{anomaly_id}/narrate",
    response_model=ResponseEnvelope[AnomalyNarrationResponse],
)
async def narrate_anomaly(
    anomaly_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_finance_ai_read),
    svc: FinanceAutomationService = Depends(get_finance_automation_service_with_ai),
) -> ResponseEnvelope[AnomalyNarrationResponse]:
    narration = await svc.narrate_anomaly(_tenant_id(current_user), anomaly_id)
    return ResponseEnvelope(
        data=AnomalyNarrationResponse(
            narration=narration["narration"],
            model_used=narration.get("model_used", ""),
        )
    )


@router.post(
    "/reminders/generate",
    response_model=ResponseEnvelope[ReminderDraftLineResponse],
)
async def generate_reminder(
    body: ReminderGenerateRequest,
    current_user: dict[str, Any] = Depends(require_finance_ai_read),
    svc: FinanceAutomationService = Depends(get_finance_automation_service_with_ai),
) -> ResponseEnvelope[ReminderDraftLineResponse]:
    reminder = await svc.generate_reminder(_tenant_id(current_user), body.invoice_id)
    return ResponseEnvelope(data=ReminderDraftLineResponse.model_validate(reminder))


@router.post(
    "/reminders/batch",
    response_model=ResponseEnvelope[ReminderDraftResponse],
)
async def batch_reminders(
    current_user: dict[str, Any] = Depends(require_finance_ai_read),
    svc: FinanceAutomationService = Depends(get_finance_automation_service_with_ai),
) -> ResponseEnvelope[ReminderDraftResponse]:
    reminders = await svc.batch_reminders(_tenant_id(current_user))
    return ResponseEnvelope(
        data=ReminderDraftResponse(
            reminders=[
                ReminderDraftLineResponse(
                    invoice_number=r.invoice_number,
                    customer_name=r.customer_name,
                    amount=r.amount,
                    days_overdue=r.days_overdue,
                    tone=r.tone,
                    subject=r.subject,
                    body=r.body,
                )
                for r in reminders
            ]
        )
    )
