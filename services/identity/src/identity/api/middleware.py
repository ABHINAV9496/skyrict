"""Middleware stack — request-id and tenant context.

TenantContextMiddleware is the SINGLE source of truth for tenant resolution:
it derives the tenant slug from the routing layer (Host subdomain in
staging/production, X-Tenant-Slug in local dev), verifies the tenant in the
database, cross-checks it against the verified JWT, and populates
TenantContext. Downstream code consumes TenantContext instead of re-reading
headers or parsing the Host again.

Exceptions raised here are converted to RFC 7807 problem+json responses via
skyrict_error_handler — exceptions thrown inside Starlette middleware do NOT
reach the route-level ExceptionMiddleware handlers.
"""

from __future__ import annotations

import re
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from identity.core.config import Environment, settings
from identity.core.constants import SKIP_AUTH_PATHS
from identity.core.exceptions import (
    SkyrictError,
    TenantContextMissingError,
    TenantDisabledError,
    TenantNotFoundError,
    TokenExpiredError,
    TokenInvalidError,
    skyrict_error_handler,
)
from identity.core.security import verify_jwt
from identity.core.tenant_context import TenantContext
from identity.db.session import async_session_factory
from identity.features.auth.security import cross_check_jwt_tenant
from identity.features.organizations.repository import TenantRepository

logger = structlog.get_logger("identity.middleware")

# Slug grammar matches the nginx routing config (infra/nginx/dev.conf):
# one label of lowercase letters, digits, and hyphens.
_TENANT_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def is_tenant_required_path(path: str) -> bool:
    """True when the path needs tenant resolution (everything except skip paths).

    Health/readiness/docs and the self-service auth paths (register, verify-email)
    are exempt; login and all business routes require a resolved tenant so the
    context exists before handlers run.
    """
    return path not in SKIP_AUTH_PATHS


def resolve_tenant_slug_from_host(host: str, *, base_domain: str) -> str | None:
    """Derive the tenant slug from a Host header (staging/production).

    Examples (base_domain="skyrict.com"):
        acme.skyrict.com       -> "acme"
        a.b.skyrict.com        -> "a"   (first label, ingress contract)
        skyrict.com            -> None  (apex is not a tenant subdomain)
        acme.skyrict.com:443   -> "acme"  (port stripped)

    Returns None when the host is not a tenant subdomain of base_domain or the
    first label is not a valid slug.
    """
    base = base_domain.strip().lower().lstrip(".")
    host_l = (host or "").strip().lower()
    if not base or not host_l:
        return None
    if ":" in host_l:
        # Strip any port before suffix matching (Host: acme.skyrict.com:443).
        host_l = host_l.rsplit(":", 1)[0]
    if not host_l.endswith(f".{base}"):
        return None
    label = host_l[: -(len(base) + 1)].split(".", 1)[0]
    if not label or not _TENANT_SLUG_RE.fullmatch(label):
        return None
    return label


def derive_tenant_slug(request: Request) -> str | None:
    """Return the routed tenant slug for this request, or None if unresolvable.

    Staging/production: derived from the Host subdomain. A client-supplied
    X-Tenant-Slug is NEVER trusted here — the header is spoofable end-to-end.

    Dev/test: taken from the X-Tenant-Slug header injected by nginx
    (infra/nginx/dev.conf), which always overwrites client input.
    """
    if settings.ENVIRONMENT in (Environment.STAGING, Environment.PRODUCTION):
        return resolve_tenant_slug_from_host(
            request.headers.get("host", ""), base_domain=settings.BASE_DOMAIN
        )
    slug = (request.headers.get("X-Tenant-Slug") or "").strip().lower()
    if not slug or not _TENANT_SLUG_RE.fullmatch(slug):
        return None
    return slug


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every request/response for tracing."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Resolve the routed tenant, cross-check the JWT, populate TenantContext.

    Flow (single source of truth — no other layer re-resolves the tenant):
      1. Skip health/ready/docs (no tenant context needed).
      2. Derive the tenant slug from the routing layer (Host / X-Tenant-Slug).
      3. Look up the tenant by slug — unknown -> TenantNotFoundError,
         disabled -> TenantDisabledError.
      4. If a Bearer token is present, verify it via security.verify_jwt() —
         the ONE AND ONLY decode path — and cross-check its tenant claim
         against the routed tenant; mismatch -> TenantMismatchError (401) and
         processing stops.
      5. Populate TenantContext (tenant_id, user_id) and bind structlog vars.
      6. After the response, clear the context and structlog vars so no tenant
         leaks into the next request.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not is_tenant_required_path(request.url.path):
            return await call_next(request)

        try:
            return await self._resolve_and_call(request, call_next)
        except SkyrictError as exc:
            # Middleware exceptions bypass ExceptionMiddleware; produce the
            # same RFC 7807 response the handlers would.
            return await skyrict_error_handler(request, exc)

    async def _resolve_and_call(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # --- 2. Derive the slug from the routing layer ---
        slug = derive_tenant_slug(request)
        if slug is None:
            raise TenantContextMissingError(
                "Tenant cannot be resolved from the request. "
                "Use a tenant subdomain (production) or X-Tenant-Slug (dev)."
            )

        # --- 3. Verify the tenant exists and is active ---
        async with async_session_factory() as session:
            tenant = await TenantRepository(session).get_by_slug(slug)
            if tenant is None:
                raise TenantNotFoundError(f"No tenant found for slug '{slug}'")
            if not tenant.is_active:
                raise TenantDisabledError(f"Tenant '{slug}' is disabled")
            routed_tenant_id = str(tenant.id)

        # --- 4. Verify the JWT (if present) and cross-check its tenant ---
        jwt_tenant_id: str | None = None
        user_id: str | None = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
            try:
                payload = verify_jwt(token)
            except (TokenExpiredError, TokenInvalidError):
                # Invalid/expired token: let route-level deps (get_current_user)
                # produce the 401. We never decode without verification.
                logger.debug(
                    "jwt_verification_failed",
                    path=request.url.path,
                    request_id=request.state.request_id,
                )
            else:
                jwt_tenant_id = payload.get("tenant_id")
                user_id = payload.get("sub")
                cross_check_jwt_tenant(jwt_tenant_id, routed_tenant_id)

        # --- 5. Populate the request-scoped context ---
        TenantContext.set(routed_tenant_id)
        TenantContext.set_user_id(user_id)
        structlog.contextvars.bind_contextvars(tenant_id=routed_tenant_id, user_id=user_id)

        try:
            response = await call_next(request)
            return response
        finally:
            TenantContext.reset()
            structlog.contextvars.unbind_contextvars("tenant_id", "user_id")
