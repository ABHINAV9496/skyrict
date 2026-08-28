"""HR/Payroll AI ORM models — one file per ``ai_*`` / ``erp_employee_documents`` table."""

from core.features.ai_hr.models.attrition_score import (
    AttritionRiskBand,
    AttritionScoreModel,
)
from core.features.ai_hr.models.compliance_check import (
    ComplianceCheckModel,
    ComplianceCheckType,
    ComplianceStatus,
)
from core.features.ai_hr.models.employee_document import (
    DocumentType,
    EmployeeDocumentModel,
)
from core.features.ai_hr.models.payroll_anomaly import (
    AnomalySeverity,
    AnomalyStatus,
    AnomalyType,
    PayrollAnomalyModel,
)

__all__ = [
    "AnomalySeverity",
    "AnomalyStatus",
    "AnomalyType",
    "AttritionRiskBand",
    "AttritionScoreModel",
    "ComplianceCheckModel",
    "ComplianceCheckType",
    "ComplianceStatus",
    "DocumentType",
    "EmployeeDocumentModel",
    "PayrollAnomalyModel",
]
