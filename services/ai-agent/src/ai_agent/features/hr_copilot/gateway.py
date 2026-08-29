"""HR gateway - read-only access to the core monolith's aggregate HR data.

The AI agent owns NO HR tables: the Copilot answers are grounded in core's
existing L1 aggregate endpoints and the tenant's leave policy, fetched over
HTTP with the CALLER's own JWT + tenant slug (spec §1.4 "AI is a proxy, not a
bypass"). The :class:`HrGatewayPort` protocol is what the engine depends on;
tests fake it, production binds :class:`HttpHrGateway`.

Aggregate-only guarantee (spec §2): the gateway calls only the L1 endpoints
(``/ai/hr/overview``, ``/ai/hr/tenure``) and the tenant leave policy
(``/hr/leave/policy``) - never any per-employee endpoint. The context it hands
back carries counts, bands, and policy figures, never a name or PII. A failed
read degrades to ``None`` so the engine can answer from whatever context IS
available instead of erroring on a partial outage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx
import structlog

from ai_agent.core.exceptions import AiUnavailableError

logger = structlog.get_logger("ai_agent.hr_gateway")


@dataclass(frozen=True, slots=True)
class HrOverviewCtx:
    """L1 headcount/tenure overview - aggregate numbers only."""

    total_headcount: int
    departments: tuple[tuple[str, int], ...]
    tenure_bands: tuple[tuple[str, int], ...]
    narrative: str


@dataclass(frozen=True, slots=True)
class HrTenureCtx:
    """L1 tenure-band summary - aggregate narrative only."""

    narrative: str


@dataclass(frozen=True, slots=True)
class HrLeavePolicyCtx:
    """The tenant's leave policy (structured, no PII)."""

    casual_days_per_year: int | None
    sick_days_per_year: int | None
    effective_from: str | None


class HrGatewayPort(Protocol):
    """Read-only aggregate HR reads, scoped by the forwarded caller's identity."""

    async def get_overview(self) -> HrOverviewCtx | None: ...
    async def get_tenure(self) -> HrTenureCtx | None: ...
    async def get_leave_policy(self) -> HrLeavePolicyCtx | None: ...


class HttpHrGateway:
    """One request's gateway: forwards the user's JWT + tenant slug to core."""

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str,
        tenant_slug: str,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._tenant_slug = tenant_slug

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._bearer_token}",
            "X-Tenant-Slug": self._tenant_slug,
        }

    def _create_client(self) -> httpx.AsyncClient:
        """Create the per-call HTTP client (overridable seam for tests)."""
        return httpx.AsyncClient(timeout=10.0)

    async def get_overview(self) -> HrOverviewCtx | None:
        payload = await self._get("/api/v1/ai/hr/overview")
        if payload is None:
            return None
        data = _envelope_data(payload)
        return HrOverviewCtx(
            total_headcount=_as_int(data.get("total_headcount"), 0),
            departments=_departments(data),
            tenure_bands=_bands(data.get("tenure_bands")),
            narrative=str(data.get("narrative") or ""),
        )

    async def get_tenure(self) -> HrTenureCtx | None:
        payload = await self._get("/api/v1/ai/hr/tenure")
        if payload is None:
            return None
        data = _envelope_data(payload)
        return HrTenureCtx(narrative=str(data.get("narrative") or ""))

    async def get_leave_policy(self) -> HrLeavePolicyCtx | None:
        payload = await self._get("/api/v1/hr/leave/policy")
        if payload is None:
            return None
        data = _envelope_data(payload)
        return HrLeavePolicyCtx(
            casual_days_per_year=_as_opt_int(data.get("casual_days_per_year")),
            sick_days_per_year=_as_opt_int(data.get("sick_days_per_year")),
            effective_from=(
                None if data.get("effective_from") is None else str(data["effective_from"])
            ),
        )

    async def _get(self, path: str) -> dict[str, object] | None:
        """GET one envelope; transport/HTTP failures degrade to None."""
        try:
            async with self._create_client() as client:
                response = await client.get(f"{self._base_url}{path}", headers=self._headers())
                if response.status_code != 200:
                    logger.warning("hr_gateway_non_ok", path=path, status=response.status_code)
                    return None
                return _as_json_dict(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("hr_gateway_unreachable", path=path)
            raise AiUnavailableError("HR service is temporarily unavailable") from exc


def _as_json_dict(value: object) -> dict[str, object]:
    """Validate a JSON body is an object (any other shape is an empty dict)."""
    return value if isinstance(value, dict) else {}


def _envelope_data(payload: dict[str, object]) -> dict[str, object]:
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _departments(data: dict[str, object]) -> tuple[tuple[str, int], ...]:
    raw = data.get("departments")
    if not isinstance(raw, list):
        return ()
    out: list[tuple[str, int]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("department_name") or "")
        count = _as_int(item.get("count"), 0)
        if name:
            out.append((name, count))
    return tuple(out)


def _bands(raw: object) -> tuple[tuple[str, int], ...]:
    if not isinstance(raw, list):
        return ()
    out: list[tuple[str, int]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append((str(item.get("band") or ""), _as_int(item.get("count"), 0)))
    return tuple(out)


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_opt_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
