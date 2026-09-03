"""Health check endpoints - /health and /ready.

Required for Kubernetes liveness and readiness probes:
  - /health - liveness: the process is up (no dependency checks).
  - /ready  - readiness: 503 until the lifespan has verified every required
    dependency (database, JWT public key) at startup, then runs a lightweight
    live probe (DB SELECT 1) before returning 200. The one-time startup
    verification itself runs in the lifespan - /ready never re-runs it, it
    only reports state and performs the cheap probe.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.api import readiness
from core.core.logging import get_logger

router = APIRouter(tags=["health"])

logger = get_logger("core.health")


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Liveness probe - is the service running?"""
    return {"status": "healthy", "service": "core"}


@router.get("/ready")
async def readiness_check() -> JSONResponse:
    """Readiness probe - is the service ready to accept traffic?

    Returns 503 until startup dependency verification has succeeded (the
    readiness gate is closed). Once verified, performs a lightweight live
    probe (DB ``SELECT 1``) and returns 200 only when it succeeds; a probe
    failure returns 503 so orchestrators can pull the pod from rotation when
    the database degrades after boot.
    """
    if not readiness.is_ready():
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "service": "core"},
        )

    try:
        await readiness.check_database()
        checks: dict[str, str] = {"database": "ok"}
    except Exception:
        logger.warning("readiness.live_check_failed", dependency="database", exc_info=True)
        checks = {"database": "failed"}

    if checks["database"] == "ok":
        return JSONResponse(
            status_code=200,
            content={"status": "ready", "service": "core", "checks": checks},
        )

    logger.warning("readiness.not_ready", checks=checks)
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "service": "core", "checks": checks},
    )
