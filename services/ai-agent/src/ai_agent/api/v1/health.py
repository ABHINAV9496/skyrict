"""Health check endpoints - /health and /ready.

Required for Kubernetes liveness and readiness probes:
  - /health - liveness: the process is up (no dependency checks).
  - /ready  - readiness: 503 until the lifespan has verified every required
    dependency (database, Redis, JWT public key) at startup, then runs
    lightweight live probes before returning 200. The one-time startup
    verification itself runs in the lifespan - /ready never re-runs it, it
    only reports state and performs the cheap probes.

Provider health is provider-NEUTRAL (SKY-57): there is deliberately no
``ollama_ok`` - configured-provider reachability surfaces under ``providers``
once the provider layer lands.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ai_agent.api import readiness
from ai_agent.core.constants import SERVICE_NAME
from ai_agent.core.logging import get_logger

router = APIRouter(tags=["health"])

logger = get_logger("ai_agent.health")


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Liveness probe - is the service running?"""
    return {"status": "healthy", "service": SERVICE_NAME}


@router.get("/ready")
async def readiness_check() -> JSONResponse:
    """Readiness probe - is the service ready to accept traffic?

    Returns 503 until startup dependency verification has succeeded (the
    readiness gate is closed). Once verified, performs lightweight live
    probes (DB ``SELECT 1``, Redis ``PING``) and returns 200 only when both
    succeed; a probe failure returns 503 so orchestrators can pull the pod
    from rotation when a dependency degrades after boot.
    """
    if not readiness.is_ready():
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "service": SERVICE_NAME},
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

    if all(value == "ok" for value in checks.values()):
        return JSONResponse(
            status_code=200,
            content={"status": "ready", "service": SERVICE_NAME, "checks": checks},
        )

    logger.warning("readiness.not_ready", checks=checks)
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "service": SERVICE_NAME, "checks": checks},
    )
