"""Middleware stack — request-id and tenant context.

TenantContextMiddleware is the SINGLE source of truth for tenant resolution:
it derives the tenant slug via the centralized ``TenantResolver`` (core),
verifies the tenant in the database, cross-checks it against the verified
JWT, and populates TenantContext. Downstream code consumes TenantContext
instead of re-reading headers or parsing the Host again.

Exceptions raised here are converted to RFC 7807 problem+json responses via
skyrict_error_handler — exceptions thrown inside Starlette middleware do NOT
reach the route-level ExceptionMiddleware handlers.
"""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

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
from identity.core.tenant_resolver import (
    TenantResolver,  # noqa: F401  # re-exported for existing callers
    derive_tenant_slug,
    resolve_tenant_slug_from_host,  # noqa: F401  # re-exported for existing callers
)
from identity.db.session import async_session_factory
from identity.features.auth.security import cross_check_jwt_tenant
from identity.features.organizations.repository import TenantRepository

logger = structlog.get_logger("identity.middleware")


def is_tenant_required_path(path: str) -> bool:
    """True when the path needs tenant resolution (everything except skip paths).

    Health/readiness/docs and the self-service auth paths (register, verify-email)
    are exempt; login and all business routes require a resolved tenant so the
    context exists before handlers run.
    """
    return path not in SKIP_AUTH_PATHS


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
