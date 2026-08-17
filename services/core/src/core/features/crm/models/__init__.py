"""CRM ORM models — one file per ``erp_*`` table (CRM-DATA-001).

Feature models are NOT re-exported from ``core.models``: importing that
package from ``core.features`` would violate the import-linter layering
contract, so the migration runner imports these models directly.
"""

from core.features.crm.models.activity import ErpCrmActivityModel
from core.features.crm.models.contact import ErpCrmContactModel
from core.features.crm.models.customer import ErpCrmCustomerModel
from core.features.crm.models.lead import ErpCrmLeadModel
from core.features.crm.models.note import ErpCrmNoteModel
from core.features.crm.models.opportunity import ErpCrmOpportunityModel
from core.features.crm.models.timeline_event import ErpCrmTimelineEventModel

__all__ = [
    "ErpCrmActivityModel",
    "ErpCrmContactModel",
    "ErpCrmCustomerModel",
    "ErpCrmLeadModel",
    "ErpCrmNoteModel",
    "ErpCrmOpportunityModel",
    "ErpCrmTimelineEventModel",
]
