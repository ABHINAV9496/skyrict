"""V1 API router — aggregates all v1 endpoint modules.

Phase 1 hosts the health/readiness endpoints, a protected ``/me`` exercise
route, and the HR & payroll feature routers (HR-BE-002). Feature routers
(inventory, purchase, sales, invoice) are added by their own ERP tickets under
``core.features.*``.
"""

from __future__ import annotations

from fastapi import APIRouter

from core.api.v1.health import router as health_router
from core.api.v1.me import router as me_router
from core.api.v1.routers.hr import router as hr_router
from core.api.v1.routers.payroll import router as payroll_router

api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(me_router)
api_router.include_router(hr_router)
api_router.include_router(payroll_router)
