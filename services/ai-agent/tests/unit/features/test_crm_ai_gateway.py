"""Unit tests for the HTTP CRM gateway adapter (httpx MockTransport)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.features.crm.gateway import HttpCrmGateway

LEAD_ID = "00000000-0000-0000-0000-000000000001"
ENTITY_ID = "00000000-0000-0000-0000-000000000002"


def _make_gateway(handler: Any) -> tuple[HttpCrmGateway, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    gateway = HttpCrmGateway(
        base_url="https://core.internal",
        bearer_token="user-token-123",
        tenant_slug="acme-corp",
    )
    gateway._create_client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        timeout=5, transport=httpx.MockTransport(transport_handler)
    )
    return gateway, seen


def _envelope(data: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, "data": data}


def _list_envelope(
    data: list[dict[str, Any]], page: int = 1, total_pages: int = 1
) -> dict[str, Any]:
    return {
        "success": True,
        "data": data,
        "meta": {"total": len(data), "page": page, "page_size": 100, "total_pages": total_pages},
    }


_LEAD = {
    "id": LEAD_ID,
    "status": "new",
    "source": "website",
    "first_name": "Ada",
    "last_name": "Lovelace",
    "email": "ada@example.com",
    "created_at": "2026-08-01T10:00:00+00:00",
}

_ACTIVITY = {
    "id": "00000000-0000-0000-0000-000000000003",
    "kind": "call",
    "completed_at": "2026-08-30T10:00:00+00:00",
    "created_at": "2026-08-29T09:30:00+00:00",
}


class TestForwarding:
    async def test_forwards_caller_token_and_tenant_slug(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope(_LEAD))

        gateway, seen = _make_gateway(handler)
        await gateway.get_lead(lead_id=uuid.UUID(LEAD_ID))

        assert seen[0].headers["Authorization"] == "Bearer user-token-123"
        assert seen[0].headers["X-Tenant-Slug"] == "acme-corp"
        assert seen[0].url.path == f"/api/v1/crm/leads/{LEAD_ID}"


class TestGetLead:
    async def test_parses_lead_fields_and_contact_signals(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope(_LEAD))

        gateway, _ = _make_gateway(handler)
        lead = await gateway.get_lead(lead_id=uuid.UUID(LEAD_ID))

        assert lead.status == "new"
        assert lead.source == "website"
        assert lead.has_name is True
        assert lead.has_email is True
        assert lead.created_at.year == 2026

    async def test_absent_contact_fields_drive_booleans_false(self) -> None:
        sparse = dict(_LEAD, first_name=None, last_name=None, email=None, source=None)

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope(sparse))

        gateway, _ = _make_gateway(handler)
        lead = await gateway.get_lead(lead_id=uuid.UUID(LEAD_ID))

        assert lead.source is None
        assert lead.has_name is False
        assert lead.has_email is False

    async def test_unreachable_core_raises_typed_unavailable(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        gateway, _ = _make_gateway(handler)
        with pytest.raises(AiUnavailableError):
            await gateway.get_lead(lead_id=uuid.UUID(LEAD_ID))


class TestListActivities:
    async def test_filters_by_entity_and_parses_completion(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["entity_type"] == "lead"
            assert request.url.params["entity_id"] == ENTITY_ID
            return httpx.Response(200, json=_list_envelope([_ACTIVITY]))

        gateway, _ = _make_gateway(handler)
        activities = await gateway.list_activities_for_entity(
            entity_type="lead", entity_id=uuid.UUID(ENTITY_ID)
        )

        assert len(activities) == 1
        activity = activities[0]
        assert activity.kind == "call"
        assert activity.completed_at is not None
        assert activity.created_at.year == 2026

    async def test_pending_activity_has_null_completed_at(self) -> None:
        pending = dict(_ACTIVITY, completed_at=None)

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_list_envelope([pending]))

        gateway, _ = _make_gateway(handler)
        activities = await gateway.list_activities_for_entity(
            entity_type="lead", entity_id=uuid.UUID(ENTITY_ID)
        )

        assert activities[0].completed_at is None
