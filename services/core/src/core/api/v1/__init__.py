"""V1 endpoint modules - health/readiness now; ERP feature routers follow."""

from core.api.v1.health import router as health_router
from core.api.v1.me import router as me_router

__all__ = ["health_router", "me_router"]
