"""Transport logic for proxying requests to the ai-agent microservice.

Pure asyncio/httpx — no FastAPI imports — so failure mapping and header
hygiene are exhaustively unit-testable with ``httpx.MockTransport``.

Security posture:
- ONLY the caller's ``Authorization: Bearer`` header and the resolved
  tenant slug are relayed. Cookies, hop-by-hop headers, and client
  fingerprint headers are never forwarded.
- ai-agent re-verifies the JWT and cross-checks it against the relayed
  slug (spec §1.4), so a spoofed slug cannot widen access.
- Transport failures (connect/timeout) raise the typed 503 problem the
  frontend mock-fallback policy consumes; upstream application errors
  pass through untouched (ai-agent speaks RFC 7807 already).
"""

from __future__ import annotations

import httpx
from fastapi.responses import Response

from core.core.exceptions import AiServiceUnavailableError


def build_forward_headers(*, authorization: str | None, tenant_slug: str | None) -> dict[str, str]:
    """The exact header set relayed upstream — nothing else survives."""
    headers: dict[str, str] = {}
    if authorization:
        headers["Authorization"] = authorization
    if tenant_slug:
        headers["X-Tenant-Slug"] = tenant_slug
    return headers


async def forward_to_ai_agent(
    client: httpx.AsyncClient,
    *,
    method: str,
    upstream_path: str,
    authorization: str | None,
    tenant_slug: str | None,
    body: bytes | None = None,
    params: httpx.QueryParams | None = None,
) -> httpx.Response:
    """Send one request to ai-agent and return its response untouched.

    Raises:
        AiServiceUnavailableError: On any transport-level failure
            (connection refused, DNS, TLS, timeout). Never on HTTP error
            statuses — those are valid upstream application responses.
    """
    headers = build_forward_headers(authorization=authorization, tenant_slug=tenant_slug)
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        return await client.request(
            method,
            upstream_path,
            content=body if body is not None else b"",
            headers=headers,
            params=params,
        )
    except httpx.TransportError as exc:
        raise AiServiceUnavailableError("AI agent service did not respond") from exc


def relay_response(upstream: httpx.Response) -> Response:
    """Materialise an upstream response as a Starlette reply.

    Status and body pass through verbatim; only Content-Type is carried
    over (ai-agent always answers JSON/problem+json).
    """
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )
