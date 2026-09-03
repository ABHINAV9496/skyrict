"""Core -> ai-agent account-code suggestion client (SKY-56/SKY-64, option B).

Mirrors ``core.features.ai_hr.attrition_client``: anonymous account options
(code + name only, never financial balances/PII) are relayed to ai-agent
``POST /api/v1/ai/finance/account-suggest``. The caller's ``Authorization``
and tenant slug are relayed so ai-agent re-verifies the JWT and cross-checks
the tenant. Transport/upstream failures surface as
:class:`AiServiceUnavailableError`; a missing/no-match suggestion is ``None``
(both are treated by the caller as "fall back to deterministic matching").
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal

import httpx

from core.core.exceptions import AiServiceUnavailableError
from core.domain.entities import (
    AccountCodeSuggestion,
    AnomalyNarration,
    ChartOfAccount,
    DraftEntry,
    DraftEntryLine,
    ReminderDraft,
)
from core.features.ai.proxy import forward_to_ai_agent

_UPSTREAM_PATH = "/api/v1/ai/finance/account-suggest"
_DRAFT_UPSTREAM_PATH = "/api/v1/ai/finance/draft-entry"
_NARRATE_UPSTREAM_PATH = "/api/v1/ai/finance/anomalies/narrate"
_REMINDER_UPSTREAM_PATH = "/api/v1/ai/finance/reminders/draft"


async def suggest_account_code_with_ai(
    client: httpx.AsyncClient,
    *,
    authorization: str | None,
    tenant_slug: str | None,
    description: str,
    accounts: Sequence[ChartOfAccount],
) -> AccountCodeSuggestion | None:
    """Ask ai-agent's LLM for the best account; ``None`` when it abstains/fails."""
    payload = {
        "description": description,
        "accounts": [{"code": a.code, "name": a.name} for a in accounts],
    }
    upstream = await forward_to_ai_agent(
        client,
        method="POST",
        upstream_path=_UPSTREAM_PATH,
        authorization=authorization,
        tenant_slug=tenant_slug,
        body=json.dumps(payload).encode("utf-8"),
    )
    if upstream.status_code >= 400:
        raise AiServiceUnavailableError("AI account-code suggestion failed")

    try:
        data = upstream.json()
    except ValueError:
        raise AiServiceUnavailableError(
            "AI account-code suggestion returned invalid JSON"
        ) from None

    code = str(data.get("suggested_code") or "").strip()
    name = str(data.get("suggested_name") or "").strip()
    confidence = data.get("confidence")
    if not code or not name or not isinstance(confidence, (int, float)):
        return None

    raw_amount = data.get("amount")
    amount: Decimal | None = None
    if isinstance(raw_amount, (int, float)) and raw_amount > 0:
        amount = Decimal(str(raw_amount))

    raw_side = str(data.get("side") or "debit").strip().lower()
    side = raw_side if raw_side in ("debit", "credit") else "debit"

    contra_code = str(data.get("contra_code") or "").strip()
    contra_name = str(data.get("contra_name") or "").strip()

    return AccountCodeSuggestion(
        description=description,
        suggested_code=code,
        suggested_name=name,
        confidence=Decimal(str(confidence)),
        reasoning=str(data.get("reasoning") or "").strip(),
        amount=amount,
        side=side,
        contra_code=contra_code,
        contra_name=contra_name,
    )


async def draft_journal_entry_with_ai(
    client: httpx.AsyncClient,
    *,
    authorization: str | None,
    tenant_slug: str | None,
    description: str,
    accounts: Sequence[ChartOfAccount],
) -> DraftEntry | None:
    """Ask ai-agent for a multi-line journal entry draft; ``None`` on abstention."""
    payload = {
        "description": description,
        "accounts": [{"code": a.code, "name": a.name} for a in accounts],
    }
    upstream = await forward_to_ai_agent(
        client,
        method="POST",
        upstream_path=_DRAFT_UPSTREAM_PATH,
        authorization=authorization,
        tenant_slug=tenant_slug,
        body=json.dumps(payload).encode("utf-8"),
    )
    if upstream.status_code >= 400:
        return None

    try:
        data = upstream.json()
    except ValueError:
        return None

    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        return None

    lines = []
    for rl in raw_lines:
        if not isinstance(rl, dict):
            continue
        code = str(rl.get("account_code") or "").strip()
        name = str(rl.get("account_name") or "").strip()
        amt = rl.get("amount")
        side = str(rl.get("side") or "debit").strip().lower()
        if not code or not isinstance(amt, (int, float)) or amt <= 0:
            continue
        if side not in ("debit", "credit"):
            side = "debit"
        lines.append(DraftEntryLine(
            account_code=code,
            account_name=name,
            amount=Decimal(str(amt)),
            side=side,
            description=str(rl.get("description") or "").strip(),
        ))

    if not lines:
        return None

    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = 0.5

    return DraftEntry(
        lines=tuple(lines),
        explanation=str(data.get("explanation") or "").strip(),
        confidence=Decimal(str(confidence)),
        reasoning=str(data.get("reasoning") or "").strip(),
        model_used=str(data.get("model_used") or "").strip(),
    )


async def narrate_anomaly_with_ai(
    client: httpx.AsyncClient,
    *,
    authorization: str | None,
    tenant_slug: str | None,
    anomaly_type: str,
    description: str,
    severity: str,
) -> AnomalyNarration | None:
    """Ask ai-agent to narrate a finance anomaly."""
    payload = {
        "anomaly_type": anomaly_type,
        "description": description,
        "severity": severity,
    }
    upstream = await forward_to_ai_agent(
        client,
        method="POST",
        upstream_path=_NARRATE_UPSTREAM_PATH,
        authorization=authorization,
        tenant_slug=tenant_slug,
        body=json.dumps(payload).encode("utf-8"),
    )
    if upstream.status_code >= 400:
        return None

    try:
        data = upstream.json()
    except ValueError:
        return None

    narration = str(data.get("narration") or "").strip()
    if not narration:
        return None

    return AnomalyNarration(
        narration=narration,
        model_used=str(data.get("model_used") or "").strip(),
    )


async def generate_reminder_with_ai(
    client: httpx.AsyncClient,
    *,
    authorization: str | None,
    tenant_slug: str | None,
    customer_name: str | None,
    invoice_number: str,
    amount: float,
    days_overdue: int,
    tone: str,
) -> ReminderDraft | None:
    """Ask ai-agent to draft a payment reminder."""
    payload = {
        "customer_name": customer_name,
        "invoice_number": invoice_number,
        "amount": amount,
        "days_overdue": days_overdue,
        "tone": tone,
    }
    upstream = await forward_to_ai_agent(
        client,
        method="POST",
        upstream_path=_REMINDER_UPSTREAM_PATH,
        authorization=authorization,
        tenant_slug=tenant_slug,
        body=json.dumps(payload).encode("utf-8"),
    )
    if upstream.status_code >= 400:
        return None

    try:
        data = upstream.json()
    except ValueError:
        return None

    subject = str(data.get("subject") or "").strip()
    body_text = str(data.get("body") or "").strip()
    if not subject or not body_text:
        return None

    return ReminderDraft(
        invoice_number=invoice_number,
        customer_name=customer_name,
        amount=Decimal(str(amount)),
        days_overdue=days_overdue,
        tone=tone,
        subject=subject,
        body=body_text,
        model_used=str(data.get("model_used") or "").strip(),
    )
