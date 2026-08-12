"""Protected endpoint exercising get_current_user.

Phase 1 ships exactly one business route so the shared auth dependencies have
a live consumer and integration tests can prove tenant isolation end-to-end.
Feature routers replace this with real ERP endpoints in their own tickets.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from core.api.deps import get_current_user

router = APIRouter(tags=["me"])


@router.get("/me")
async def me(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Return the current authenticated user's identity.

    Exercises the full auth chain: JWT verification, token-vs-routed-tenant
    cross-check, and tenant context population. Intentionally minimal — it is
    a dependency smoke route, not a feature.
    """
    return {
        "user_id": current_user["user_id"],
        "tenant_id": current_user["tenant_id"],
    }
