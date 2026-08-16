"""V1 API router — aggregates all v1 endpoint modules.

Phase 1 hosts health/readiness, a protected ``/me`` exercise route, and the
feature routers for HR & payroll (HR-BE-002), inventory (INV-BE-002), and
finance (FIN-BE-002). Feature routers for purchase and sales arrive in their
own ERP tickets under ``core.features.*``.
"""

from __future__ import annotations

from fastapi import APIRouter

from core.api.v1.health import router as health_router
from core.api.v1.me import router as me_router
from core.api.v1.routers.hr import router as hr_router
from core.api.v1.routers.payroll import router as payroll_router
from core.features.finance.router import router as finance_router
from core.features.inventory.router import router as inventory_router

api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(me_router)
api_router.include_router(hr_router)
api_router.include_router(payroll_router)
api_router.include_router(finance_router)
api_router.include_router(inventory_router)
