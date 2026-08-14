"""FastAPI dependency injection — get_tenant_context, get_current_user, require_permission.

The api layer is the sole composition point: shared authentication and
authorization dependencies live here, mirroring identity/api/deps.py. Core owns
its ERP RBAC tables, so ``require_permission`` resolves roles -> permissions
from the database at request time (never from JWT claims) through
:class:`RbacRepository`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core.core.security import cross_check_jwt_tenant, verify_jwt
from core.core.tenant_context import TenantContext
from core.db.rbac import RbacRepository, grants_permission
from core.db.session import get_db
from core.features.audit.repository import AuditRepository
from core.features.inventory.repository import InventoryRepository
from skyrict_common.exceptions import AuthenticationError, PermissionDeniedError

if TYPE_CHECKING:
    from core.features.audit.service import AuditService
    from core.features.inventory.service import InventoryService

security = HTTPBearer(auto_error=False)


def get_tenant_context() -> str:
    """Return the current request's tenant ID (resolved by the middleware)."""
    return TenantContext.get()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    """Extract and verify the JWT from the Authorization header.

    Uses ``verify_jwt`` — the ONE AND ONLY decode path. The routed tenant is
    consumed from ``TenantContext`` (resolved once by the middleware) and the
    JWT-vs-routed cross-check is enforced here again as defense in depth, so a
    token can never be used against a different tenant even if a route is
    reached without going through the middleware.

    Raises:
        AuthenticationError: If no token, the token is invalid/expired, or the
            token ``type`` is not ``access``.
        TenantContextMissingError: If the middleware hasn't resolved a tenant.
        TenantMismatchError: If the token's tenant claim differs from the routed tenant.
    """
    if credentials is None:
        raise AuthenticationError("Missing Authorization header")

    payload = verify_jwt(credentials.credentials)

    if payload.get("type") != "access":
        raise AuthenticationError("Invalid token type")

    # Single source of truth: the routed tenant was resolved by the middleware.
    routed_tenant_id = TenantContext.get()
    cross_check_jwt_tenant(payload.get("tenant_id"), routed_tenant_id)
    TenantContext.set_user_id(payload["sub"])

    return {
        "user_id": payload["sub"],
        "tenant_id": routed_tenant_id,
        "token_payload": payload,
    }


def require_permission(permission: str) -> Callable[[], Awaitable[dict[str, Any]]]:
    """Dependency factory — returns a dependency that checks a specific permission.

    Resolves the user's grants from the database (core_roles / core_user_roles)
    at request time and fails closed with ``PermissionDeniedError`` when the
    required key (or the wildcard ``"*"``) is not present.
    """

    async def _check(
        current_user: dict[str, Any] = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> dict[str, Any]:
        granted = await RbacRepository(db).resolve_user_permissions(
            user_id=current_user["user_id"],
            tenant_id=current_user["tenant_id"],
        )
        if not grants_permission(granted, permission):
            raise PermissionDeniedError(f"Missing required permission: {permission}")
        return current_user

    return _check


async def get_adjustment_authority(
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> bool:
    """True when the caller may approve above-threshold inventory adjustments.

    Resolves ``erp.inventory.adjust.approve`` (or the ``*`` wildcard) from the
    DB grants at request time. The threshold itself is enforced by the service
    (``settings.INVENTORY_ADJUST_APPROVE_THRESHOLD``) — this dependency only
    answers "may this user approve?".
    """
    from core.core.permissions import ERP_INVENTORY_ADJUST_APPROVE

    granted = await RbacRepository(db).resolve_user_permissions(
        user_id=current_user["user_id"],
        tenant_id=current_user["tenant_id"],
    )
    return grants_permission(granted, ERP_INVENTORY_ADJUST_APPROVE)


# --- Repository deps ---


def get_audit_repo(db: AsyncSession = Depends(get_db)) -> AuditRepository:
    return AuditRepository(db)


def get_audit_service(audit_repo: AuditRepository = Depends(get_audit_repo)) -> AuditService:
    from core.features.audit.service import AuditService

    return AuditService(audit_repo)


def get_inventory_repo(db: AsyncSession = Depends(get_db)) -> InventoryRepository:
    return InventoryRepository(db)


def get_inventory_service(
    inventory_repo: InventoryRepository = Depends(get_inventory_repo),
    audit_service: AuditService = Depends(get_audit_service),
) -> InventoryService:
    from core.features.inventory.service import InventoryService

    return InventoryService(inventory_repo, audit_service)
