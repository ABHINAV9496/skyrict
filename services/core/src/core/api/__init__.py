"""API layer - FastAPI application wiring (deps, middleware, lifespan, routes)."""

from core.api.deps import get_current_user, get_tenant_context, require_permission

__all__ = ["get_current_user", "get_tenant_context", "require_permission"]
