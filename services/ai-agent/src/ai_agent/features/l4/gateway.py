"""L4 core gateway - fetch the payroll-base snapshot from the core monolith (SKY-93).

Unlike the HR Copilot gateway which gracefully degrades on 403 (aggregate
vs per-employee data tiers), the L4 gateway is *strict*: the caller has
already passed the ``erp.hr.ai.planning`` gate both at this service's router
(database-resolved, direct API hits get 403) and at the core proxy edge, so a
403 or transport failure here is a hard error (misconfiguration or outage).

The protocol (:class:`L4CoreGatewayPort`) is what the service depends on;
tests fake it, production binds :class:`HttpL4CoreGateway`.
"""

from __future__ import annotations

from typing import Protocol

import httpx
import structlog

from ai_agent.core.config import settings
from ai_agent.core.core_http import CoreHttpTransport
from ai_agent.core.exceptions import AiUnavailableError

logger = structlog.get_logger("ai_agent.l4_gateway")


class L4CoreGatewayPort(Protocol):
    """Read-only access to the core monolith's L4 payroll-base endpoint."""

    async def get_payroll_base(self, as_of: str) -> dict[str, object]: ...


class HttpL4CoreGateway(CoreHttpTransport):
    """Per-request gateway: forwards the user's JWT + tenant slug to core."""

    def __init__(
        self,
        *,
        bearer_token: str,
        tenant_slug: str,
    ) -> None:
        super().__init__(
            base_url=str(settings.INVENTORY_SERVICE_URL),
            bearer_token=bearer_token,
            tenant_slug=tenant_slug,
            timeout_seconds=settings.INVENTORY_SERVICE_TIMEOUT_SECONDS,
        )

    async def get_payroll_base(self, as_of: str) -> dict[str, object]:
        """Fetch the payroll-base envelope and return the unwrapped ``data`` dict.

        Strict: transport failure or non-200 → AiUnavailableError.
        """
        params: dict[str, str] = {}
        if as_of:
            params["as_of"] = as_of
        try:
            async with self._create_client() as client:
                response = await client.get(
                    f"{self._base_url}/api/v1/ai/hr/l4/payroll-base",
                    headers=self._headers(),
                    params=params,
                )
        except httpx.HTTPError as exc:
            logger.warning("l4_gateway_unreachable")
            raise AiUnavailableError("Core HR service is temporarily unavailable") from exc
        if response.status_code != 200:
            logger.warning("l4_gateway_non_ok", status=response.status_code)
            raise AiUnavailableError(f"Core HR service returned status {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            logger.warning("l4_gateway_bad_body")
            raise AiUnavailableError("Core HR service returned an unusable response") from exc
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise AiUnavailableError("Core HR service returned an invalid payload")
        return data


__all__ = ["HttpL4CoreGateway", "L4CoreGatewayPort"]
