"""V1 API router — aggregates all v1 endpoint modules.

Phase 1 hosts only the health/readiness endpoints, a protected ``/me``
exercise route, and the finance feature router (FIN-BE-002). Additional ERP
feature routers are added by their own tickets under ``core.features.*``.
"""

from __future__ import annotations

from fastapi import APIRouter

from core.api.v1.health import router as health_router
from core.api.v1.me import router as me_router
from core.features.finance.router import router as finance_router

api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(me_router)
api_router.include_router(finance_router)
