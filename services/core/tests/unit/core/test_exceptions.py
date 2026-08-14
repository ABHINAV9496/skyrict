"""Exception-to-status mapping tests — the RFC 7807 tenant error contract.

Tenant error mapping (ERP-FND-001):
  missing tenant context -> 400 tenant-context-missing
  token/routed tenant mismatch -> 401 tenant-mismatch
  unknown tenant slug -> 404 tenant-not-found
  disabled tenant -> 403 tenant-disabled
"""

from __future__ import annotations

from core.core.exceptions import _status_and_type
from skyrict_common.exceptions import (
    PermissionDeniedError,
    TenantContextMissingError,
    TenantDisabledError,
    TenantMismatchError,
    TenantNotFoundError,
)


class TestTenantErrorMapping:
    def test_missing_context_is_400(self) -> None:
        status, problem_type = _status_and_type(TenantContextMissingError("missing"))
        assert status == 400
        assert problem_type.endswith("/tenant-context-missing")

    def test_mismatch_is_401(self) -> None:
        status, problem_type = _status_and_type(TenantMismatchError("mismatch"))
        assert status == 401
        assert problem_type.endswith("/tenant-mismatch")

    def test_unknown_tenant_is_404(self) -> None:
        status, problem_type = _status_and_type(TenantNotFoundError("unknown"))
        assert status == 404
        assert problem_type.endswith("/tenant-not-found")

    def test_disabled_tenant_is_403(self) -> None:
        status, problem_type = _status_and_type(TenantDisabledError("disabled"))
        assert status == 403
        assert problem_type.endswith("/tenant-disabled")

    def test_missing_permission_is_403_authorization_error(self) -> None:
        # Spec error table (hr-payroll.md §7): valid JWT, missing permission →
        # 403 `authorization-error` (PermissionDeniedError subclasses
        # AuthorizationError; the MRO walk must land on the same URI).
        status, problem_type = _status_and_type(PermissionDeniedError("no grant"))
        assert status == 403
        assert problem_type.endswith("/authorization-error")
