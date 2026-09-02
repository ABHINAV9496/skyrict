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
)
from core.features.finance.ports import AuditSink, FinanceRepositoryPort
from core.features.finance.schemas import (
    AccountCodeSuggestionResponse,
    AnomalyResponse,
    ArAgingResponse,
    CashflowProjectionResponse,
    CloseChecklistResponse,
    ComparativePnlResponse,
    DuplicateGroupResponse,
    HealthScoreResponse,
    JournalEntryResponse,
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


def _tenant_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["tenant_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


def _user_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["user_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


AiSuggester = Callable[[str, Sequence[ChartOfAccount]], Awaitable[AccountCodeSuggestion | None]]


@dataclass
class FinanceAutomationService:
    """Business rules for finance automation widgets (thin over the repo)."""

    repo: FinanceRepositoryPort
    audit: AuditSink
    ai_suggest: AiSuggester | None = field(default=None)

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
    current_user: dict[str, Any] = Depends(require_finance_read),
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
