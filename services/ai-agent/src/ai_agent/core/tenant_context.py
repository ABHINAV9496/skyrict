"""ContextVar-based TenantContext — request-scoped tenant isolation.

The middleware is the SINGLE source of truth for tenant resolution: it resolves
the tenant once (Host subdomain in production, X-Tenant-Slug in local dev),
verifies it against the JWT, and populates this context. Every downstream layer
— engines, repositories, route dependencies — consumes the tenant from here
and never re-reads headers or parses the Host again.

Uses ContextVar (not threading.local) so async tasks and event-loop workers are
isolated; the context is cleared after every request to prevent leakage.
"""

from __future__ import annotations

from contextvars import ContextVar

from fastapi import Request

from skyrict_common.exceptions import TenantContextMissingError

# Request-scoped context vars. Defaults are immutable (None) and every accessor
# returns what was set — callers can never mutate shared state.
_current_tenant_id: ContextVar[str | None] = ContextVar("current_tenant_id", default=None)
_current_tenant_slug: ContextVar[str | None] = ContextVar("current_tenant_slug", default=None)
_current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


class TenantContext:
    """Access and set the request-scoped tenant security context.

    Usage in middleware:
        TenantContext.set(tenant_id)
        TenantContext.set_user_id(user_id)  # when a JWT was verified

    Usage in services/repos:
        tenant_id = TenantContext.get()  # raises if not set

    tenant_id ALWAYS comes from the routing layer cross-checked against the
    verified JWT claims — NEVER from user input (prompt-injection defense,
    inventory AI spec §5.6).
    """

    # --- tenant_id (required) ---

    @staticmethod
    def set(tenant_id: str) -> None:
        """Set the current tenant ID for this request context."""
        _current_tenant_id.set(tenant_id)

    @staticmethod
    def get() -> str:
        """Get the current tenant ID. Raises if not set.

        Call this from engines/repos that MUST be tenant-scoped.
        """
        tid = _current_tenant_id.get()
        if tid is None:
            raise TenantContextMissingError(
                "Tenant context is not set. "
                "Ensure TenantContextMiddleware runs before route handlers."
            )
        return tid

    @staticmethod
    def get_optional() -> str | None:
        """Get the current tenant ID without raising. Use sparingly."""
        return _current_tenant_id.get()

    # --- tenant slug (optional — needed to forward calls to core) ---

    @staticmethod
    def set_tenant_slug(slug: str | None) -> None:
        """Set the routed tenant slug (the X-Tenant-Slug / subdomain value).

        Downstream HTTP gateways forward it so the core monolith resolves the
        same tenant (its middleware accepts X-Tenant-Slug in dev/test).
        """
        _current_tenant_slug.set(slug)

    @staticmethod
    def get_tenant_slug() -> str | None:
        """Get the routed tenant slug, or None when resolution skipped it."""
        return _current_tenant_slug.get()

    # --- user_id (optional — set when a JWT was verified) ---

    @staticmethod
    def set_user_id(user_id: str | None) -> None:
        """Set the authenticated user ID for this request (None = anonymous)."""
        _current_user_id.set(user_id)

    @staticmethod
    def get_user_id() -> str | None:
        """Get the authenticated user ID, or None for anonymous requests."""
        return _current_user_id.get()

    # --- lifecycle ---

    @staticmethod
    def reset() -> None:
        """Clear the whole context — called by middleware at request end."""
        _current_tenant_id.set(None)
        _current_tenant_slug.set(None)
        _current_user_id.set(None)


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


def get_current_tenant(request: Request) -> str:
    """FastAPI dependency that returns the current tenant ID.

    Use in route signatures:
        @router.get("/items")
        async def list_items(tenant_id: str = Depends(get_current_tenant)):
            ...

    Raises:
        TenantContextMissingError: If TenantContextMiddleware hasn't set the tenant.
    """
    return TenantContext.get()
