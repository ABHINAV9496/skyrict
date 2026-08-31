"""CRM gateway - read access to the core monolith's CRM API (SKY-61).

The AI agent owns NO CRM tables: leads/opportunities/activities live in core's
shared database. Deterministic scoring, deal health, and the NL CRM actions all
read through core's existing HTTP API (the "AI is a proxy, not a bypass" rule).
:class:`CrmGatewayPort` is what engines depend on; tests fake it, production
binds :class:`HttpCrmGateway`.

Adapter notes (verified against core's routers):
- base path ``/api/v1/crm``; list responses use the shared envelope with a
  ``meta.total_pages`` pagination field, single responses wrap data in
  ``ResponseEnvelope``;
- timestamps arrive as ISO-8601 strings (tolera a trailing ``Z``);
- entity types for activities are lowercase enums (``lead``, ``opportunity``…).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

import httpx
import structlog

from ai_agent.core.exceptions import AiUnavailableError

logger = structlog.get_logger("ai_agent.crm_gateway")

# Activities page through core with this guard so a pathological history cannot
# make one scoring/health call loop forever. 20 pages x 100 rows = 2000 items.
_MAX_CATALOG_PAGES = 20
_CATALOG_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class LeadRef:
    """The lead fields the scoring engine needs (verified against LeadResponse)."""

    id: uuid.UUID
    status: str
    source: str | None
    created_at: datetime
    # Contact-presence signals used by the ``fit`` sub-score (no PII beyond
    # booleans ever leaves the gateway; raw values stay in core).
    has_name: bool
    has_email: bool


@dataclass(frozen=True, slots=True)
class ActivityRef:
    """One CRM activity row - engagement/recency signals for scoring."""

    id: uuid.UUID
    kind: str
    completed_at: datetime | None
    created_at: datetime


class CrmGatewayPort(Protocol):
    """Read-only CRM queries, scoped by the forwarded caller's identity."""

    async def get_lead(self, *, lead_id: uuid.UUID) -> LeadRef: ...
    async def list_activities_for_entity(
        self, *, entity_type: str, entity_id: uuid.UUID
    ) -> list[ActivityRef]: ...


class HttpCrmGateway:
    """One request's gateway: forwards the caller's JWT + tenant slug to core."""

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
            # Core resolves tenants via subdomain in prod, X-Tenant-Slug in
            # dev/test; forwarding the slug keeps behavior identical either way.
            "X-Tenant-Slug": self._tenant_slug,
        }

    async def get_lead(self, *, lead_id: uuid.UUID) -> LeadRef:
        payload = await self._get_single(f"/leads/{lead_id}")
        created_at = _parse_datetime(payload["created_at"])
        first_name = payload.get("first_name")
        last_name = payload.get("last_name")
        email = payload.get("email")
        return LeadRef(
            id=lead_id,
            status=str(payload["status"]),
            source=None if payload.get("source") is None else str(payload["source"]),
            created_at=created_at,
            has_name=bool(first_name) or bool(last_name),
            has_email=bool(email),
        )

    async def list_activities_for_entity(
        self, *, entity_type: str, entity_id: uuid.UUID
    ) -> list[ActivityRef]:
        items: list[ActivityRef] = []
        params = {"entity_type": entity_type, "entity_id": str(entity_id)}
        for page in range(1, _MAX_CATALOG_PAGES + 1):
            page_items = await self._get_list("/activities", page=page, extra=params)
            items.extend(_parse_activity(item) for item in page_items.items)
            if page >= page_items.total_pages:
                break
        return items

    def _create_client(self) -> httpx.AsyncClient:
        """Create the per-call HTTP client (overridable seam for tests)."""
        return httpx.AsyncClient(timeout=10.0)

    async def _get_single(self, path: str) -> dict[str, object]:
        try:
            async with self._create_client() as client:
                response = await client.get(
                    f"{self._base_url}/api/v1/crm{path}", headers=self._headers()
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("crm_gateway_unreachable", path=path)
            raise AiUnavailableError("CRM service is temporarily unavailable") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning("crm_gateway_bad_body", path=path)
            raise AiUnavailableError("CRM service returned an unusable response") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise AiUnavailableError("CRM service returned an unusable response")
        return cast("dict[str, object]", payload["data"])

    async def _get_list(
        self, path: str, *, page: int, extra: dict[str, str] | None = None
    ) -> _ListPage:
        params: dict[str, str] = {"page": str(page), "page_size": str(_CATALOG_PAGE_SIZE)}
        if extra:
            params.update(extra)
        try:
            async with self._create_client() as client:
                response = await client.get(
                    f"{self._base_url}/api/v1/crm{path}",
                    params=params,
                    headers=self._headers(),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("crm_gateway_unreachable", path=path)
            raise AiUnavailableError("CRM service is temporarily unavailable") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning("crm_gateway_bad_body", path=path)
            raise AiUnavailableError("CRM service returned an unusable response") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise AiUnavailableError("CRM service returned an unusable response")
        meta = payload.get("meta")
        total_pages = meta.get("total_pages") if isinstance(meta, dict) else None
        if not isinstance(total_pages, int):
            raise AiUnavailableError("CRM service returned an unusable response")
        return _ListPage(items=payload["data"], total_pages=total_pages)


class _ListPage:
    """One validated envelope page: raw items plus the pagination fact."""

    __slots__ = ("items", "total_pages")

    def __init__(self, *, items: list[dict[str, object]], total_pages: int) -> None:
        self.items = items
        self.total_pages = total_pages


def _parse_datetime(raw: object) -> datetime:
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def _parse_activity(item: dict[str, object]) -> ActivityRef:
    completed_raw = item.get("completed_at")
    return ActivityRef(
        id=uuid.UUID(str(item["id"])),
        kind=str(item["kind"]),
        completed_at=None if completed_raw is None else _parse_datetime(completed_raw),
        created_at=_parse_datetime(item["created_at"]),
    )
