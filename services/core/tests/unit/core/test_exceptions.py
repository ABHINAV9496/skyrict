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
    ConflictError,
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


class TestConflictMapping:
    def test_conflict_is_409(self) -> None:
        status, problem_type = _status_and_type(ConflictError("conflict"))
        assert status == 409
        assert problem_type.endswith("/conflict")
