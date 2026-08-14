"""FastAPI dependency injection — get_tenant_context, get_current_user, require_permission.

The api layer is the sole composition point: shared authentication and
authorization dependencies live here, mirroring identity/api/deps.py. Core owns
its ERP RBAC tables, so ``require_permission`` resolves roles -> permissions
from the database at request time (never from JWT claims) through
:class:`RbacRepository`.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core.core.logging import get_logger
from core.core.security import cross_check_jwt_tenant, verify_jwt
from core.core.tenant_context import TenantContext
from core.db.rbac import RbacRepository, grants_permission
from core.db.session import get_db
from skyrict_common.exceptions import AuthenticationError, PermissionDeniedError

if TYPE_CHECKING:
    from core.core.audit_service import AuditService
    from core.features.hr.repository import HrRepository
    from core.features.hr.service import DepartmentService, EmployeeService, LeaveService
    from core.features.payroll.service import PayrollService

logger = get_logger("core.deps")

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


def get_tenant_id() -> uuid.UUID:
    """Return the current request's tenant id as a UUID (resolved by the middleware)."""
    return uuid.UUID(TenantContext.get())


class _NoopIdentityUserPort:
    """Phase 1 identity-port stand-in for :class:`IdentityUserPort`.

    The concrete validator calls the identity service (in-process or HTTP) and
    is wired here at the composition root — the one place to swap it when the
    identity integration ticket lands. Phase 1 deliberately fails OPEN (logs a
    warning) so ``POST /hr/employees`` works without an identity round-trip;
    until then ``user_id`` on hire is accepted as-is.
    """

    async def validate_user(self, user_id: uuid.UUID, *, tenant_id: uuid.UUID) -> None:
        logger.warning(
            "identity.validate_user_noop",
            user_id=str(user_id),
            tenant_id=str(tenant_id),
            message="identity-service user validation is not wired yet (Phase 1)",
        )


def get_hr_repo(db: AsyncSession = Depends(get_db)) -> HrRepository:
    from core.db.sequence_repository import SequenceRepository
    from core.features.hr.repository import HrRepository

    return HrRepository(db, next_sequence=SequenceRepository(db).next_value)


def get_audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    from core.core.audit_service import AuditService
    from core.db.audit_repository import AuditLogRepository

    return AuditService(AuditLogRepository(db))


def get_department_service(
    repo: HrRepository = Depends(get_hr_repo),
    audit: AuditService = Depends(get_audit_service),
) -> DepartmentService:
    from core.features.hr.service import DepartmentService

    return DepartmentService(repository=repo, audit=audit)


def get_employee_service(
    repo: HrRepository = Depends(get_hr_repo),
    audit: AuditService = Depends(get_audit_service),
) -> EmployeeService:
    from core.features.hr.service import EmployeeService

    return EmployeeService(repository=repo, audit=audit, identity=_NoopIdentityUserPort())


def get_leave_service(
    repo: HrRepository = Depends(get_hr_repo),
    audit: AuditService = Depends(get_audit_service),
) -> LeaveService:
    from core.features.hr.service import LeaveService

    return LeaveService(repository=repo, audit=audit)


def get_payroll_service(
    db: AsyncSession = Depends(get_db),
    audit: AuditService = Depends(get_audit_service),
) -> PayrollService:
    """Payroll service with the HR repository injected as the leave ledger.

    ``HrRepository`` implements ``LeaveLedgerPort.approved_unpaid_days`` (the
    one sanctioned cross-feature read), so the payroll feature never imports
    the HR feature directly.
    """
    from core.db.sequence_repository import SequenceRepository
    from core.features.hr.repository import HrRepository
    from core.features.payroll.repository import PayrollRepository
    from core.features.payroll.service import PayrollService

    return PayrollService(
        repository=PayrollRepository(db, next_sequence=SequenceRepository(db).next_value),
        leave_ledger=HrRepository(db, next_sequence=SequenceRepository(db).next_value),
        audit=audit,
    )
