"""Health check endpoints - /health and /ready.

Required for Kubernetes liveness and readiness probes:
  - /health - liveness: the process is up (no dependency checks).
  - /ready  - readiness: 503 until the lifespan has verified every required
    dependency (database, Redis, JWT keys) at startup, then runs lightweight
    live probes (DB SELECT 1 + Redis PING) before returning 200. The
    one-time startup verification itself runs in the lifespan - /ready never
    re-runs it, it only reports state and performs cheap probes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from identity.api import readiness
from identity.core.logging import get_logger

router = APIRouter(tags=["health"])

logger = get_logger("identity.health")


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Liveness probe - is the service running?"""
    return {"status": "healthy", "service": "identity"}


@router.get("/ready")
async def readiness_check() -> JSONResponse:
    """Readiness probe - is the service ready to accept traffic?

    Returns 503 until startup dependency verification has succeeded (the
    readiness gate is closed). Once verified, performs lightweight live
    probes (DB ``SELECT 1`` + Redis ``PING``) and returns 200 only when both
    succeed; a probe failure returns 503 so orchestrators can pull the pod
    from rotation when a dependency degrades after boot.
    """
    if not readiness.is_ready():
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "service": "identity"},
        )

    checks: dict[str, str] = {}
    try:
        await readiness.check_database()
        checks["database"] = "ok"
    except Exception:
        logger.warning("readiness.live_check_failed", dependency="database", exc_info=True)
        checks["database"] = "failed"

    try:
        await readiness.check_redis()
        checks["redis"] = "ok"
    except Exception:
        logger.warning("readiness.live_check_failed", dependency="redis", exc_info=True)
        checks["redis"] = "failed"

    if checks["database"] == "ok" and checks["redis"] == "ok":
        return JSONResponse(
            status_code=200,
            content={"status": "ready", "service": "identity", "checks": checks},
        )

    logger.warning("readiness.not_ready", checks=checks)
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "service": "identity", "checks": checks},
    )
