"""Dashboard telemetry gateway - read-only access to Core's event summary.

The AI agent owns NO dashboard/telemetry tables: the per-widget event counts
and the suggestion-readiness decision both live in the Core monolith
(BUG-AI-002). The :class:`DashboardGatewayPort` protocol is what the service
depends on; tests fake it, production binds :class:`HttpDashboardGateway`.

Core's ``GET /api/v1/dashboards/me/events/summary`` returns the per-widget
counts plus a ``suggestion_ready`` flag driven by Core's own minimum-event
threshold - the AI agent never re-implements the 50-event bar.

The AI is a proxy, never a bypass (SKY-57 rule): every call forwards the
CALLER's JWT and tenant slug, so Core enforces the caller's own access on the
telemetry read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx
import structlog

from ai_agent.core.core_http import CoreHttpTransport
from ai_agent.core.exceptions import (
    AiUnavailableError,
    AuthorizationError,
    NotFoundError,
)

logger = structlog.get_logger("ai_agent.dashboard_gateway")


@dataclass(frozen=True, slots=True)
class WidgetTelemetry:
    """Event counts for one widget (as reported by Core)."""

    widget_id: str
    total_events: int
    distinct_events: int


@dataclass(frozen=True, slots=True)
class EventSummary:
    """Telemetry plus Core's own readiness signal."""

    items: list[WidgetTelemetry]
    suggestion_ready: bool


class DashboardGatewayPort(Protocol):
    """Read the tenant's dashboard telemetry, scoped by the caller identity."""

    async def get_event_summary(self) -> EventSummary: ...


class HttpDashboardGateway(CoreHttpTransport):
    """One request's gateway: forwards the user's JWT + tenant slug to Core."""

    async def get_event_summary(self) -> EventSummary:
        try:
            async with self._create_client() as client:
                response = await client.get(
                    f"{self._base_url}/api/v1/dashboards/me/events/summary",
                    headers=self._headers(),
                )
                _raise_for_response(response)
        except httpx.TransportError as exc:
            logger.warning("dashboard_gateway_unreachable", path="events/summary")
            raise AiUnavailableError("Dashboard telemetry is temporarily unavailable") from exc
        payload = _payload(response)
        raw_items = payload.get("items")
        items: list[object] = raw_items if isinstance(raw_items, list) else []
        return EventSummary(
            items=[
                WidgetTelemetry(
                    widget_id=str(item["widget_id"]),
                    total_events=int(item["total_events"]),
                    distinct_events=int(item["distinct_events"]),
                )
                for item in items
                if isinstance(item, dict)
            ],
            suggestion_ready=bool(payload.get("suggestion_ready", False)),
        )


def _raise_for_response(response: httpx.Response) -> None:
    """Map Core's HTTP status to the matching domain exception."""
    if response.is_success:
        return
    status = response.status_code
    if status in (401, 403):
        raise AuthorizationError("Not authorized to read dashboard telemetry")
    if status == 404:
        raise NotFoundError("Dashboard telemetry was not found")
    logger.warning("dashboard_gateway_rejected", status=status)
    raise AiUnavailableError("Dashboard telemetry returned an unusable response")


def _payload(response: httpx.Response) -> dict[str, object]:
    """Parse the summary body; any anomaly is a typed 503."""
    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("dashboard_gateway_bad_body")
        raise AiUnavailableError("Dashboard telemetry returned an unusable response") from exc
    if not isinstance(payload, dict):
        raise AiUnavailableError("Dashboard telemetry returned an unusable response")
    return payload
