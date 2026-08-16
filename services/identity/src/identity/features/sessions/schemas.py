"""Session request/response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from identity.core.user_agent import UNKNOWN, DeviceInfo, parse_user_agent
from identity.domain.entities import Session


class SessionResponse(BaseModel):
    """Session data returned in API responses.

    ``device``/``device_type`` are the legacy human-facing labels; the
    structured ``browser_name``/``os_name``/``device_family``/
    ``device_model`` fields are machine-friendly and ``None`` whenever the
    fact genuinely could not be determined.
    """

    id: UUID
    user_id: UUID
    tenant_id: UUID
    ip_address: str | None = None
    user_agent: str | None = None
    status: str
    is_trusted: bool = False
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime | None = None
    device: str | None = None
    device_type: str | None = None
    browser_name: str | None = None
    browser_version: str | None = None
    os_name: str | None = None
    os_version: str | None = None
    device_family: str | None = None
    device_model: str | None = None

    model_config = {"from_attributes": True}


def _device_from_info(session: Session) -> DeviceInfo:
    """Structured device facts, preferring the facts captured at login.

    ``device_info`` JSONB written by the current login flow carries the
    structured fields (plus Client Hints refinements). Sessions recorded
    before that flow fell back to re-parsing the User-Agent, which also
    upgrades them to the current, more accurate classifier.
    """
    info = session.device_info or {}
    if "browser_name" in info or "device_family" in info:
        return DeviceInfo(
            browser=str(info.get("browser") or UNKNOWN),
            browser_version=str(info.get("browser_version") or ""),
            os=str(info.get("os") or UNKNOWN),
            os_version=str(info.get("os_version") or ""),
            device=str(info.get("device") or UNKNOWN),
            device_type=str(info.get("device_type") or "unknown"),
            browser_name=info.get("browser_name"),
            os_name=info.get("os_name"),
            device_family=info.get("device_family"),
            device_model=info.get("device_model"),
        )
    return parse_user_agent(session.user_agent)


def session_to_response(session: Session) -> SessionResponse:
    """Map a session entity to its API response, adding device facts.

    This is the single session→response mapper shared by the sessions and
    members routers so every consumer sees identical device metadata.
    """
    device = _device_from_info(session)
    assert session.id is not None
    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        tenant_id=session.tenant_id,
        ip_address=session.ip_address,
        user_agent=session.user_agent,
        status=session.status.value,
        is_trusted=session.is_trusted,
        created_at=session.created_at,
        last_active_at=session.last_active_at,
        expires_at=session.expires_at,
        device=device.device,
        device_type=device.device_type,
        browser_name=device.browser_name,
        browser_version=device.browser_version,
        os_name=device.os_name,
        os_version=device.os_version,
        device_family=device.device_family,
        device_model=device.device_model,
    )


class SessionListResponse(BaseModel):
    """Paginated session list."""

    sessions: list[SessionResponse]
    total: int


class SessionRevokeRequest(BaseModel):
    """POST /sessions/{id}/revoke — revoke a specific session."""

    reason: str | None = None


class SessionRevokeAllRequest(BaseModel):
    """POST /sessions/revoke-all — revoke all sessions except current."""

    except_current: bool = True


class SessionTrustRequest(BaseModel):
    """PATCH /sessions/{session_id}/trusted — mark a device as recognized."""

    is_trusted: bool
