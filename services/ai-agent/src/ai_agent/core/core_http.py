"""Shared HTTP transport for core-monolith adapters (D1 consolidation).

The feature gateways and the reindex/ingest loaders all talk to the core
monolith over the same transport mechanics: an http(s) base URL, a per-call
``httpx.AsyncClient`` behind an overridable ``_create_client`` seam, and the
bearer token + ``X-Tenant-Slug`` request headers. This base owns ONLY those
genuinely identical mechanics (verified across all 13 call sites).

Deliberately NOT centralized here - each feature adapter keeps its own,
verified-different behavior:
- envelope parsing/strictness and pagination scheme (page/total_pages vs
  offset/limit vs empty-page break);
- error mapping, ``AiUnavailableError`` message text, and log event names;
- money/uuid coercion (fallback-zero vs None-preserving vs strict-raise);
- the documents gateway's m2m token + byte-stream model (no envelope).

Gateways and loaders inherit the transport; every existing ``_create_client``
test seam (MockTransport swap) keeps working unchanged.
"""

from __future__ import annotations

import httpx


class CoreHttpTransport:
    """Transport-only base for core-monolith HTTP adapters.

    Owns:
    - http(s) base-URL validation + normalization (``rstrip("/")``);
    - the shared bearer + ``X-Tenant-Slug`` request headers;
    - per-call ``httpx.AsyncClient`` creation behind the ``_create_client``
      test seam (tests swap it for a MockTransport; production uses the
      per-call client exactly as before).
    """

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str,
        tenant_slug: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not base_url.strip().lower().startswith(("http://", "https://")):
            raise ValueError("base_url must be an http(s) URL")
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._tenant_slug = tenant_slug
        self._timeout_seconds = max(timeout_seconds, 1.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._bearer_token}",
            # Core resolves tenants via subdomain in prod, X-Tenant-Slug in
            # dev/test; forwarding the slug keeps behavior identical either way.
            "X-Tenant-Slug": self._tenant_slug,
        }

    def _create_client(self) -> httpx.AsyncClient:
        """Create the per-call HTTP client (overridable seam for tests)."""
        return httpx.AsyncClient(timeout=self._timeout_seconds)
