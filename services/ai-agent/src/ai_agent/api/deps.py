"""FastAPI dependencies — the composition root for request-scoped security.

The AI agent service enforces AUTHENTICATION (verified JWT + tenant
cross-check). Authorization is enforced at the core monolith edge — the
``/api/v1/ai/*`` proxy resolves permissions (erp.ai.invoke plus module keys)
BEFORE forwarding, so a request that reaches this service has already passed
the permission gate (SKY-57: AI is a proxy, not a bypass).

This module is the only place that turns verified claims into handler inputs.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPBearer

from ai_agent.core.security import cross_check_jwt_tenant, verify_jwt
from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.session import get_db as get_db  # explicit re-export: THE db dependency
from skyrict_common.exceptions import AuthenticationError

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Any = Depends(security),
) -> dict[str, Any]:
    """Verify the Bearer JWT and return the normalized caller identity.

    The token's tenant claim is cross-checked against the routed tenant
    (defense in depth on top of the middleware check).
    """
    if credentials is None:
        raise AuthenticationError("Missing Authorization header")
    payload = verify_jwt(credentials.credentials)
    if payload.get("type") != "access":
        raise AuthenticationError("Invalid token type")
    routed_tenant_id = TenantContext.get()
    cross_check_jwt_tenant(payload.get("tenant_id"), routed_tenant_id)
    user_id = uuid.UUID(payload["sub"])  # normalized once here
    return {"user_id": user_id, "tenant_id": routed_tenant_id, "token_payload": payload}


def get_request_id(request: Request) -> str:
    """Return the request ID attached by RequestIdMiddleware."""
    return getattr(request.state, "request_id", "")
