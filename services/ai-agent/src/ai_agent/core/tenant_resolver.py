"""Centralized tenant slug resolution — the single place that maps a request
to a tenant slug.

The middleware is the only layer allowed to resolve tenants, and it delegates
here so the derivation logic (Host subdomain vs injected header, slug grammar,
reserved/platform slugs) lives in one testable module. Downstream engines and
repositories never re-read headers or re-parse the Host.

Two routing contracts (identical to core/identity):
  - staging/production: the tenant slug is the first label of the Host
    subdomain (acme.skyrict.com -> "acme"). A client-supplied X-Tenant-Slug
    is NEVER trusted here — it is spoofable end-to-end.
  - dev/test: the slug comes from the X-Tenant-Slug header injected by the
    local nginx, which always overwrites client input.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ai_agent.core.config import Environment, settings
from ai_agent.core.constants import RESERVED_SLUGS

if TYPE_CHECKING:
    from starlette.requests import Request

# Slug grammar matches the nginx routing config: one label of lowercase
# letters, digits, and hyphens.
_TENANT_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


class TenantResolver:
    """Resolve a tenant slug from a Host header or an injected slug header.

    Args:
        base_domain: Production tenant base domain (e.g. "skyrict.com"). The
            first label of a Host like acme.skyrict.com is the tenant slug.
            Ignored in dev/test, which resolve from X-Tenant-Slug.
        reserved_slugs: Platform-owned slugs that are never valid tenants.
    """

    def __init__(
        self,
        *,
        base_domain: str,
        reserved_slugs: frozenset[str] = RESERVED_SLUGS,
    ) -> None:
        self._base_domain = base_domain.strip().lower().lstrip(".")
        self._reserved_slugs = reserved_slugs

    def resolve_from_host(self, host: str) -> str | None:
        """Derive the tenant slug from a Host header (staging/production).

        Examples (base_domain="skyrict.com"):
            acme.skyrict.com       -> "acme"
            a.b.skyrict.com        -> "a"   (first label, ingress contract)
            skyrict.com            -> None  (apex is not a tenant subdomain)
            web.skyrict.com        -> None  (reserved platform host)
            acme.skyrict.com:443   -> "acme"  (port stripped)

        Returns None when the host is not a tenant subdomain of base_domain,
        the first label is not a valid slug, or it is a reserved platform slug.
        """
        base = self._base_domain
        host_l = (host or "").strip().lower()
        if not base or not host_l:
            return None
        if ":" in host_l:
            host_l = host_l.rsplit(":", 1)[0]
        if not host_l.endswith(f".{base}"):
            return None
        label = host_l[: -(len(base) + 1)].split(".", 1)[0]
        if not label or not _TENANT_SLUG_RE.fullmatch(label):
            return None
        if label in self._reserved_slugs:
            return None
        return label

    def resolve_from_header(self, slug: str | None) -> str | None:
        """Derive the tenant slug from the X-Tenant-Slug header (dev/test).

        The header is injected by the local nginx, which always overwrites
        client input, so it is trusted in dev/test only.
        """
        value = (slug or "").strip().lower()
        if not value or not _TENANT_SLUG_RE.fullmatch(value):
            return None
        if value in self._reserved_slugs:
            return None
        return value

    def resolve(self, request: Request) -> str | None:
        """Return the routed tenant slug for this request, or None.

        Staging/production: derived from the Host subdomain; a client-supplied
        X-Tenant-Slug is never trusted. Dev/test: taken from the header.
        """
        if settings.ENVIRONMENT in (Environment.STAGING, Environment.PRODUCTION):
            return self.resolve_from_host(request.headers.get("host", ""))
        return self.resolve_from_header(request.headers.get("X-Tenant-Slug"))


def derive_tenant_slug(request: Request) -> str | None:
    """Module function using the live ``settings``.

    Resolves the tenant for the request according to the current environment.
    """
    return TenantResolver(base_domain=settings.BASE_DOMAIN).resolve(request)
