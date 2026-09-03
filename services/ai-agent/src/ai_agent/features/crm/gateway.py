"""CRM gateway - read access to the core monolith's CRM API (SKY-61).

The AI agent owns NO CRM tables: leads/opportunities/activities live in core's
shared database. Deterministic scoring, deal health, and the NL CRM actions all
read through core's existing HTTP API (the "AI is a proxy, not a bypass" rule).
:class:`CrmGatewayPort` is what engines depend on; tests fake it, production
binds :class:`HttpCrmGateway`.

Security guarantee: every read forwards the CALLER's JWT + tenant slug. Core
re-enforces ``erp.crm.read``/``erp.crm.write`` permissions, tenant isolation
(RLS + explicit tenant filter), and CRM owner/team/ALL row-scoping on each
endpoint. The AI therefore receives exactly the leads/opportunities the acting
user may see in the web UI - a ``standard_user`` sees only their own records, an
admin sees the whole tenant. Raw contact fields (email/phone/company) and deal
amounts are surfaced because callers with ``erp.crm.read`` can already view them
in the UI; the agent is a proxy, never a bypass.

Adapter notes (verified against core's routers):
- base path ``/api/v1/crm``; list responses use the shared envelope with a
  ``meta.total_pages`` pagination field, single responses wrap data in
  ``ResponseEnvelope``;
- timestamps arrive as ISO-8601 strings (tolerate a trailing ``Z``); money
  arrives as a ``[amount-string, currency]`` tuple (core's ``MoneyOutput``);
- entity types for activities are lowercase enums (``lead``, ``opportunity``…).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
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
    """A lead plus the contact fields core returns for ``erp.crm.read`` holders.

    ``has_name``/``has_email`` remain for the deterministic scoring engine (it
    needs presence signals, not PII); the raw values are also carried so the
    agent can answer with the same detail a permitted UI user can see.
    """

    id: uuid.UUID
    status: str
    source: str | None
    created_at: datetime
    owner_id: uuid.UUID | None
    # Contact-presence signals used by the ``fit`` sub-score.
    has_name: bool
    has_email: bool
    # Raw contact fields core returns to ``erp.crm.read`` holders (never used
    # by the scoring engine; surfaced by the agent's conversational context).
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    # Human-facing label for the follow-up draft (scan path only).
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class OpportunityRef:
    """A deal plus the monetary fields core returns for ``erp.crm.read`` holders.

    ``has_amount`` remains for the deal-health engine (presence signal only);
    ``amount``/``currency`` carry the real value so the agent can report
    pipeline value like a permitted UI user can.
    """

    id: uuid.UUID
    stage: str
    probability: int
    has_amount: bool
    created_at: datetime
    owner_id: uuid.UUID | None
    # Core sets ``updated_at`` on every stage change, so it is a deterministic
    # proxy for when the deal last moved stage (no cross-service timeline parse).
    last_stage_change_at: datetime
    expected_close_date: date | None
    # Real deal value (None when core omits it). Decimal(19,4) semantics are
    # preserved; never a float.
    amount: Decimal | None = None
    currency: str | None = None
    # Human-facing label for the follow-up draft (scan path only).
    display_name: str | None = None


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
    async def get_opportunity(self, *, opportunity_id: uuid.UUID) -> OpportunityRef: ...
    async def list_activities_for_entity(
        self, *, entity_type: str, entity_id: uuid.UUID
    ) -> list[ActivityRef]: ...
    async def list_leads(self, *, page: int = 1) -> list[LeadRef]: ...
    async def list_opportunities(self, *, page: int = 1) -> list[OpportunityRef]: ...

    async def query(
        self,
        *,
        resource: str,
        filters: dict[str, str] | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, object]: ...


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
        return _parse_lead(payload)

    async def get_opportunity(self, *, opportunity_id: uuid.UUID) -> OpportunityRef:
        payload = await self._get_single(f"/opportunities/{opportunity_id}")
        return _parse_opportunity(payload)

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

    async def list_leads(self, *, page: int = 1) -> list[LeadRef]:
        """All leases for the current scope; owner_id lets the scan assign owners."""
        items: list[LeadRef] = []
        for page_no in range(page, _MAX_CATALOG_PAGES + 1):
            payload = await self._get_list("/leads", page=page_no)
            items.extend(_parse_lead(item) for item in payload.items)
            if page_no >= payload.total_pages:
                break
        return items

    async def list_opportunities(self, *, page: int = 1) -> list[OpportunityRef]:
        """All opportunities for the current scope; owner_id lets the scan assign owners."""
        items: list[OpportunityRef] = []
        for page_no in range(page, _MAX_CATALOG_PAGES + 1):
            payload = await self._get_list("/opportunities", page=page_no)
            items.extend(_parse_opportunity(item) for item in payload.items)
            if page_no >= payload.total_pages:
                break
        return items

    async def query(
        self,
        *,
        resource: str,
        filters: dict[str, str] | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, object]:
        """Generic read of one CRM list resource through the scoped endpoint.

        ``resource`` is a validated slug (e.g. ``leads``, ``opportunities``) -
        never a full path, so no traversal/query injection can reach core. The
        caller's JWT + tenant slug are forwarded, so core still enforces
        ``erp.crm.read``, tenant isolation, and owner/team row-scoping.
        """
        if not resource or "/" in resource or resource.startswith("."):
            raise AiUnavailableError("CRM resource name is invalid")
        params = {"page": str(page), "page_size": str(_CATALOG_PAGE_SIZE)}
        if resource != "activities":
            params["page_size"] = str(page_size)
        for key, value in (filters or {}).items():
            params[key] = value
        try:
            async with self._create_client() as client:
                response = await client.get(
                    f"{self._base_url}/api/v1/crm/{resource}",
                    params=params,
                    headers=self._headers(),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("crm_gateway_query_unreachable", resource=resource)
            raise AiUnavailableError("CRM service is temporarily unavailable") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning("crm_gateway_query_bad_body", resource=resource)
            raise AiUnavailableError("CRM service returned an unusable response") from exc
        if not isinstance(payload, dict):
            raise AiUnavailableError("CRM service returned an unusable response")
        return cast("dict[str, object]", payload)

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


def _parse_optional_uuid(raw: object) -> uuid.UUID | None:
    if raw is None:
        return None
    return uuid.UUID(str(raw))


def _parse_lead(item: dict[str, object]) -> LeadRef:
    first_name = item.get("first_name")
    last_name = item.get("last_name")
    email = item.get("email")
    company = item.get("company")
    display = _build_lead_display(first_name, last_name, company)
    return LeadRef(
        id=uuid.UUID(str(item["id"])),
        status=str(item["status"]),
        source=None if item.get("source") is None else str(item["source"]),
        created_at=_parse_datetime(item["created_at"]),
        owner_id=_parse_optional_uuid(item.get("owner_id")),
        has_name=bool(first_name) or bool(last_name),
        has_email=bool(email),
        first_name=None if first_name is None else str(first_name),
        last_name=None if last_name is None else str(last_name),
        email=None if email is None else str(email),
        phone=None if item.get("phone") is None else str(item["phone"]),
        company=None if company is None else str(company),
        display_name=display,
    )


def _parse_opportunity(item: dict[str, object]) -> OpportunityRef:
    expected_raw = item.get("expected_close_date")
    amount, currency = _parse_money(item.get("amount"), item.get("currency"))
    return OpportunityRef(
        id=uuid.UUID(str(item["id"])),
        stage=str(item["stage"]),
        probability=int(str(item["probability"])),
        has_amount=item.get("amount") is not None,
        created_at=_parse_datetime(item["created_at"]),
        owner_id=_parse_optional_uuid(item.get("owner_id")),
        last_stage_change_at=_parse_datetime(item["updated_at"]),
        expected_close_date=(
            None if expected_raw is None else date.fromisoformat(str(expected_raw))
        ),
        amount=amount,
        currency=currency,
        display_name=None if item.get("name") is None else str(item["name"]),
    )


def _parse_money(raw: object, currency_raw: object) -> tuple[Decimal | None, str | None]:
    """Parse core's ``[amount-string, currency]`` money tuple into Decimal/currency.

    Core serializes money as a two-element tuple; a plain number is also
    tolerated (single-currency legacy payloads). Returns ``(None, None)`` when
    ``raw`` is absent so callers can distinguish "no value" from "zero".
    """
    currency = None if currency_raw is None else str(currency_raw)
    if isinstance(raw, list | tuple) and len(raw) >= 1:
        try:
            return Decimal(str(raw[0])), currency
        except (TypeError, ValueError, ArithmeticError):
            return None, currency
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            return Decimal(str(raw)), currency
        except (TypeError, ValueError, ArithmeticError):
            return None, currency
    return None, currency


def _build_lead_display(first_name: object, last_name: object, company: object) -> str | None:
    """Best-effort display label from the list payload (PII only in scan path)."""
    parts = [part for part in (first_name, last_name) if part]
    name = " ".join(str(p) for p in parts)
    if company:
        return f"{name} ({company})" if name else str(company)
    return name or None
