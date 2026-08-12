"""ContextVar-based TenantContext — request-scoped tenant isolation.

The middleware is the SINGLE source of truth for tenant resolution: it resolves
the tenant once (Host subdomain in production, X-Tenant-Slug in local dev),
verifies it against the JWT, and populates this context. Every downstream layer
— services, repositories, route dependencies — consumes the tenant from here
and never re-reads headers or parses the Host again.

Uses ContextVar (not threading.local) so async tasks and event-loop workers are
isolated; the context is cleared after every request to prevent leakage.
"""

from __future__ import annotations

from contextvars import ContextVar

from fastapi import Request

from skyrict_common.exceptions import TenantContextMissingError

# Request-scoped context vars. Defaults are immutable (None / empty tuple) and
# every accessor returns a copy so callers can never mutate shared state.
_current_tenant_id: ContextVar[str | None] = ContextVar("current_tenant_id", default=None)
_current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)
_current_roles: ContextVar[tuple[str, ...]] = ContextVar("current_roles", default=())
_current_permissions: ContextVar[tuple[str, ...]] = ContextVar("current_permissions", default=())


class TenantContext:
    """Access and set the request-scoped tenant security context.

    Usage in middleware:
        TenantContext.set(tenant_id)
        TenantContext.set_user_id(user_id)  # when a JWT was verified

    Usage in services/repos:
        tenant_id = TenantContext.get()  # raises if not set

    Roles/permissions may be populated lazily by authorization code (e.g. after
    a DB lookup) via set_roles()/set_permissions(); consumers should use
    get_roles()/get_permissions() rather than re-querying the database.
    """

    # --- tenant_id (required) ---

    @staticmethod
    def set(tenant_id: str) -> None:
        """Set the current tenant ID for this request context."""
        _current_tenant_id.set(tenant_id)

    @staticmethod
    def get() -> str:
        """Get the current tenant ID. Raises if not set.

        Call this from services/repos that MUST be tenant-scoped.
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

    # --- user_id (optional — set when a JWT was verified) ---

    @staticmethod
    def set_user_id(user_id: str | None) -> None:
        """Set the authenticated user ID for this request (None = anonymous)."""
        _current_user_id.set(user_id)

    @staticmethod
    def get_user_id() -> str | None:
        """Get the authenticated user ID, or None for anonymous requests."""
        return _current_user_id.get()

    # --- roles (optional — populated lazily) ---

    @staticmethod
    def set_roles(roles: list[str] | tuple[str, ...]) -> None:
        """Set the user's roles within the current tenant (lazy, optional)."""
        _current_roles.set(tuple(roles))

    @staticmethod
    def get_roles() -> list[str]:
        """Get the user's roles within the current tenant (possibly empty)."""
        return list(_current_roles.get())

    # --- permissions (optional — populated lazily) ---

    @staticmethod
    def set_permissions(permissions: list[str] | tuple[str, ...]) -> None:
        """Set the user's permissions within the current tenant (lazy, optional)."""
        _current_permissions.set(tuple(permissions))

    @staticmethod
    def get_permissions() -> list[str]:
        """Get the user's permissions within the current tenant (possibly empty)."""
        return list(_current_permissions.get())

    # --- lifecycle ---

    @staticmethod
    def reset() -> None:
        """Clear the whole context — called by middleware at request end."""
        _current_tenant_id.set(None)
        _current_user_id.set(None)
        _current_roles.set(())
        _current_permissions.set(())


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
