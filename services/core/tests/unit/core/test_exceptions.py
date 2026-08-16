"""Exception-to-status mapping tests — the RFC 7807 tenant error contract.

Tenant error mapping (ERP-FND-001):
  missing tenant context -> 400 tenant-context-missing
  token/routed tenant mismatch -> 401 tenant-mismatch
  unknown tenant slug -> 404 tenant-not-found
  disabled tenant -> 403 tenant-disabled
"""

from __future__ import annotations

from core.core.exceptions import (
    DuplicateSkuError,
    InsufficientStockError,
    MovementImmutableError,
    TransferRequiresDistinctWarehousesError,
    _status_and_type,
)
from skyrict_common.exceptions import (
    ConflictError,
    PermissionDeniedError,
    TenantContextMissingError,
    TenantDisabledError,
    TenantMismatchError,
    TenantNotFoundError,
    ValidationError,
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

    def test_missing_permission_is_403_permission_denied(self) -> None:
        status, problem_type = _status_and_type(PermissionDeniedError("no grant"))
        assert status == 403
        assert problem_type.endswith("/permission-denied")


class TestConflictMapping:
    """INV-BE-002: ledger conflicts surface as RFC 7807 409 (not a 500)."""

    def test_conflict_base_maps_to_409(self) -> None:
        status, problem_type = _status_and_type(ConflictError("boom"))
        assert status == 409
        assert problem_type.endswith("/conflict")

    def test_insufficient_stock_is_409(self) -> None:
        status, problem_type = _status_and_type(InsufficientStockError())
        assert status == 409
        assert problem_type.endswith("/conflict")
        assert InsufficientStockError().code == "INSUFFICIENT_STOCK"

    def test_duplicate_sku_is_409(self) -> None:
        status, problem_type = _status_and_type(DuplicateSkuError())
        assert status == 409
        assert problem_type.endswith("/conflict")
        assert DuplicateSkuError().code == "DUPLICATE_SKU"

    def test_movement_immutable_is_409(self) -> None:
        status, problem_type = _status_and_type(MovementImmutableError())
        assert status == 409
        assert problem_type.endswith("/conflict")
        assert MovementImmutableError().code == "MOVEMENT_IMMUTABLE"


class TestValidationMapping:
    def test_validation_base_maps_to_422(self) -> None:
        status, problem_type = _status_and_type(ValidationError("bad"))
        assert status == 422
        assert problem_type.endswith("/validation-error")

    def test_transfer_same_warehouse_is_422(self) -> None:
        status, problem_type = _status_and_type(TransferRequiresDistinctWarehousesError())
        assert status == 422
        assert problem_type.endswith("/validation-error")
        assert (
            TransferRequiresDistinctWarehousesError().code
            == "TRANSFER_REQUIRES_DISTINCT_WAREHOUSES"
        )
