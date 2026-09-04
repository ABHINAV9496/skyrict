"""HR ORM models - one file per ``erp_*`` table (HR-DATA-001)."""

from core.features.hr.models.attendance_record import AttendanceRecordModel
from core.features.hr.models.department import DepartmentModel
from core.features.hr.models.employee import EmployeeModel, EmploymentStatus
from core.features.hr.models.leave_balance import LeaveBalanceModel
from core.features.hr.models.leave_movement import LeaveMovementModel
from core.features.hr.models.leave_policy import LeavePolicyModel
from core.features.hr.models.leave_request import LeaveRequestModel, LeaveRequestStatus
from core.features.hr.models.leave_type import LeaveTypeModel

__all__ = [
    "AttendanceRecordModel",
    "DepartmentModel",
    "EmployeeModel",
    "EmploymentStatus",
    "LeaveBalanceModel",
    "LeaveMovementModel",
    "LeavePolicyModel",
    "LeaveRequestModel",
    "LeaveRequestStatus",
    "LeaveTypeModel",
]
