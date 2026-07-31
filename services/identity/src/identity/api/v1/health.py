"""Health check endpoints — /health and /ready.

Required for Kubernetes liveness and readiness probes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Liveness probe — is the service running?"""
    return {"status": "healthy", "service": "identity"}


@router.get("/ready")
async def readiness_check() -> dict[str, Any]:
    """Readiness probe — is the service ready to accept traffic?

    In production, check DB connectivity, Redis, etc.
    """
    return {"status": "ready", "service": "identity"}
