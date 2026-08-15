"""CRM ORM models — one file per ``erp_*`` table (CRM-DATA-001).

Feature models are NOT re-exported from ``core.models``: importing that
package from ``core.features`` would violate the import-linter layering
contract, so the migration runner imports these models directly.
"""

from core.features.crm.models.customer import ErpCrmCustomerModel
from core.features.crm.models.lead import ErpCrmLeadModel
from core.features.crm.models.opportunity import ErpCrmOpportunityModel

__all__ = [
    "ErpCrmCustomerModel",
    "ErpCrmLeadModel",
    "ErpCrmOpportunityModel",
]
