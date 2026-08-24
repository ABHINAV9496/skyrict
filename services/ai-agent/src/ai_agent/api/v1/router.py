"""V1 API router — aggregates all v1 endpoint modules.

The scaffold ships health/readiness; the AI routers (query, suggestions,
anomalies) mount here as their commits land (SKY-57).
"""

from __future__ import annotations

from fastapi import APIRouter

from ai_agent.api.v1.health import router as health_router

api_router = APIRouter()

api_router.include_router(health_router)
