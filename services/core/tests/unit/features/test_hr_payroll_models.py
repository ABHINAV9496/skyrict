"""HR/Payroll ORM models (HR-DATA-001) - metadata contract checks.

Pure unit tests (no database). They pin the model metadata that migration
0005 and the integration tests rely on: table names, the ``(tenant_id, id)``
composite-PK convention, the immutability of ledger/entry tables, and native
enum usage (``create_type=False`` - the enum types are created by the
migration, never by the models).
"""

from __future__ import annotations

import pytest

from core.features.hr.models.department import DepartmentModel
from core.features.hr.models.employee import EmployeeModel, EmploymentStatus
from core.features.hr.models.leave_balance import LeaveBalanceModel
from core.features.hr.models.leave_movement import LeaveMovementModel
from core.features.hr.models.leave_request import LeaveRequestModel, LeaveRequestStatus
from core.features.hr.models.leave_type import LeaveTypeModel
from core.features.payroll.models.compensation import CompensationModel
from core.features.payroll.models.payroll_entry import PayrollEntryModel
from core.features.payroll.models.payroll_run import (
    PayrollRounding,
    PayrollRunModel,
    PayrollRunStatus,
)
from core.features.payroll.models.payroll_settings import PayrollSettingsModel

pytestmark = pytest.mark.unit

IMMUTABLE_MODELS = (LeaveMovementModel, PayrollEntryModel)
MUTABLE_MODELS = (
    DepartmentModel,
    EmployeeModel,
    LeaveTypeModel,
    LeaveRequestModel,
    LeaveBalanceModel,
    CompensationModel,
    PayrollRunModel,
    PayrollSettingsModel,
)
ALL_MODELS = (*MUTABLE_MODELS, *IMMUTABLE_MODELS)


@pytest.mark.parametrize(
    ("model", "table"),
    [
        (DepartmentModel, "erp_departments"),
        (EmployeeModel, "erp_employees"),
        (LeaveTypeModel, "erp_leave_types"),
        (LeaveRequestModel, "erp_leave_requests"),
        (LeaveMovementModel, "erp_leave_movements"),
        (LeaveBalanceModel, "erp_leave_balances"),
        (CompensationModel, "erp_compensation"),
        (PayrollRunModel, "erp_payroll_runs"),
        (PayrollEntryModel, "erp_payroll_entries"),
        (PayrollSettingsModel, "erp_payroll_settings"),
    ],
)
def test_model_table_names(model: type, table: str) -> None:
    assert model.__tablename__ == table


@pytest.mark.parametrize("model", ALL_MODELS)
def test_composite_primary_key_is_tenant_id_plus_id(model: type) -> None:
    assert [c.name for c in model.__table__.primary_key.columns] == ["tenant_id", "id"]


@pytest.mark.parametrize("model", ALL_MODELS)
def test_every_table_is_tenant_scoped(model: type) -> None:
    assert "tenant_id" in model.__table__.columns


def test_immutable_models_have_no_updated_at() -> None:
    for model in IMMUTABLE_MODELS:
        assert "updated_at" not in model.__table__.columns
        assert "created_at" in model.__table__.columns


def test_mutable_models_have_created_and_updated_at() -> None:
    for model in MUTABLE_MODELS:
        assert "created_at" in model.__table__.columns
        assert "updated_at" in model.__table__.columns


@pytest.mark.parametrize(
    ("column_type", "db_type"),
    [
        (EmployeeModel.__table__.c.employment_status.type, "erp_employment_status"),
        (LeaveRequestModel.__table__.c.status.type, "erp_leave_request_status"),
        (PayrollRunModel.__table__.c.status.type, "erp_payroll_run_status"),
        (PayrollSettingsModel.__table__.c.rounding.type, "erp_payroll_rounding"),
    ],
)
def test_native_enum_types_are_declared_by_migration_only(column_type, db_type: str) -> None:
    # The enum types are created by migration 0005, never by the models: the
    # DB-level type name must match, and ``create_type=False`` is what stops a
    # ``create_all`` from re-creating them. The attribute is a transient
    # constructor kwarg (not stored) in SQLAlchemy 2.0, so we pin the name and
    # native-enum flag here; the integration suite proves the types exist in
    # the real database after the migration runs.
    assert column_type.name == db_type
    assert column_type.native_enum is True


@pytest.mark.parametrize(
    ("enum_cls", "expected"),
    [
        (EmploymentStatus, ("active", "on_leave", "terminated")),
        (LeaveRequestStatus, ("pending", "approved", "rejected", "cancelled")),
        (PayrollRunStatus, ("draft", "computed", "approved", "paid", "void")),
        (PayrollRounding, ("nearest", "up", "down")),
    ],
)
def test_enum_member_values(enum_cls: type, expected: tuple[str, ...]) -> None:
    assert tuple(member.value for member in enum_cls) == expected


def test_immutable_ledger_has_no_updated_at_server_side() -> None:
    for model in IMMUTABLE_MODELS:
        created = model.__table__.c.created_at
        assert created.server_default is not None
        assert created.onupdate is None
