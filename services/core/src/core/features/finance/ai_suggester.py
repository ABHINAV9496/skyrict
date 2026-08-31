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
from core.domain.entities import AccountCodeSuggestion, ChartOfAccount
from core.features.ai.proxy import forward_to_ai_agent

_UPSTREAM_PATH = "/api/v1/ai/finance/account-suggest"


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

    return AccountCodeSuggestion(
        description=description,
        suggested_code=code,
        suggested_name=name,
        confidence=Decimal(str(confidence)),
        reasoning=str(data.get("reasoning") or "").strip(),
        amount=amount,
        side=side,
    )
