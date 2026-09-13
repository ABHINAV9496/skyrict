"""Approval workflow ORM models - one file per ``erp_*`` table (SKY-92).

Feature models are NOT re-exported from ``core.models``: importing that
package from ``core.features`` would violate the import-linter layering
contract, so the migration runner imports these models directly.
"""

from core.features.approval_workflow.models.definition import ErpApprovalWorkflowDefinitionModel

__all__ = [
    "ErpApprovalWorkflowDefinitionModel",
]
