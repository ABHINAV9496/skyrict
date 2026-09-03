"""Finance gateway — read access to the core monolith's finance API (FIN-AI-001).

The AI agent owns NO finance tables: revenue, expenses, P&L, and AR aging live
in core's shared database. The Finance Assistant reads through core's existing
HTTP API (the "AI is a proxy, not a bypass" rule). :class:`FinanceGatewayPort`
is what the delegator depends on; tests fake it, production binds
:class:`HttpFinanceGateway`.

Adapter notes (verified against core's routers):
- base path ``/api/v1/finance``; responses use the shared ResponseEnvelope;
- P&L: ``GET /reports/profit-and-loss?from_date=...&to_date=...``;
- AR aging: ``GET /automation/aging?as_of=...`` (finance automation endpoint).
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

import httpx
import structlog

from ai_agent.core.exceptions import AiUnavailableError

logger = structlog.get_logger("ai_agent.finance_gateway")

_BASE_FINANCE_PATH = "/api/v1/finance"


class FinanceGatewayPort(Protocol):
    """Read-only finance data the Finance Assistant answers from."""

    async def get_pnl(self, from_date: date, to_date: date) -> str: ...
    async def get_aging(self, as_of: date) -> str: ...


class HttpFinanceGateway:
    """HTTP adapter over core's finance + automation report endpoints."""

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str,
        tenant_slug: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._tenant_slug = tenant_slug
        self._headers = {
            "accept": "application/json",
            "authorization": f"Bearer {bearer_token}",
        }
        if tenant_slug:
            self._headers["x-tenant-slug"] = tenant_slug

    async def get_pnl(self, from_date: date, to_date: date) -> str:
        path = (
            f"{_BASE_FINANCE_PATH}/reports/profit-and-loss"
            f"?from_date={from_date.isoformat()}&to_date={to_date.isoformat()}"
        )
        return await self._fetch(path)

    async def get_aging(self, as_of: date) -> str:
        path = f"{_BASE_FINANCE_PATH}/automation/aging?as_of={as_of.isoformat()}"
        return await self._fetch(path)

    async def _fetch(self, path: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}{path}", headers=self._headers)
        except httpx.HTTPError as exc:
            logger.warning("finance_gateway.http_error", path=path, error=str(exc))
            raise AiUnavailableError("finance data unavailable") from exc
        if resp.status_code >= 400:
            logger.warning("finance_gateway.http_status", path=path, status=resp.status_code)
            raise AiUnavailableError(f"finance data unavailable ({resp.status_code})")
        return resp.text
