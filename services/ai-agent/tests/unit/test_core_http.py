"""Unit tests for the shared core-monolith HTTP transport base (D1).

The base owns ONLY the transport mechanics that are genuinely identical
across the core call sites: http(s) base-URL validation/normalization, the
bearer + X-Tenant-Slug headers, and the per-call client seam. All envelope
parsing, pagination, error mapping, and coercion stay in the feature
adapters (they are verified-different and covered by their own suites).
"""

from __future__ import annotations

import httpx
import pytest

from ai_agent.core.core_http import CoreHttpTransport


def _transport(**overrides: object) -> CoreHttpTransport:
    kwargs: dict[str, object] = {
        "base_url": "https://core.internal/",
        "bearer_token": "token-123",
        "tenant_slug": "acme-corp",
    }
    kwargs.update(overrides)
    return CoreHttpTransport(**kwargs)  # type: ignore[arg-type]


def test_base_url_normalized_and_headers_forward_identity() -> None:
    transport = _transport(base_url="https://core.internal/")
    assert transport._base_url == "https://core.internal"
    headers = transport._headers()
    assert headers == {
        "Authorization": "Bearer token-123",
        "X-Tenant-Slug": "acme-corp",
    }


def test_base_url_must_be_http_or_https() -> None:
    with pytest.raises(ValueError, match="http"):
        _transport(base_url="ftp://core.internal")
    with pytest.raises(ValueError, match="http"):
        _transport(base_url="not-a-url")


def test_timeout_seconds_floored_at_one_second() -> None:
    low = _transport(timeout_seconds=0.2)
    assert low._timeout_seconds == 1.0
    normal = _transport(timeout_seconds=12.0)
    assert normal._timeout_seconds == 12.0


def test_create_client_seam_timeout_and_override() -> None:
    transport = _transport(timeout_seconds=7.5)
    client = transport._create_client()
    assert isinstance(client, httpx.AsyncClient)
    assert client.timeout == httpx.Timeout(7.5)

    # Subclasses/tests swap the seam for a MockTransport; the base must
    # keep that overridable without touching the rest of the adapter.
    replaced = _transport()
    replaced._create_client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    )
    assert isinstance(replaced._create_client(), httpx.AsyncClient)
