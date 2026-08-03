"""Authorization service — permission checks, RBAC enforcement.

Pure and stateless: callers resolve the subject's active state (and, later,
their roles) and pass it in, so the roles feature never depends on another
feature's repository.
"""

from __future__ import annotations

from skyrict_common.exceptions import AuthorizationError


class AuthorizationService:
    """Handles permission checks and RBAC enforcement."""

    def check_permission(self, *, user_is_active: bool, permission: str, tenant_id: str) -> bool:
        """Check whether an active user has a specific permission in their tenant.

        Returns True if authorized, raises AuthorizationError if not.
        """
        if not user_is_active:
            raise AuthorizationError("User account is disabled")
        # TODO: Check the user's roles -> permissions against the required permission.
        return True

    def require_permission(self, *, user_is_active: bool, permission: str, tenant_id: str) -> None:
        """Like check_permission but always raises on failure."""
        self.check_permission(
            user_is_active=user_is_active, permission=permission, tenant_id=tenant_id
        )
