"""Sales ORM models — one file per ``erp_*`` table (CRM-DATA-001).

Feature models are NOT re-exported from ``core.models``: importing that
package from ``core.features`` would violate the import-linter layering
contract, so the migration runner imports these models directly.
"""

from core.features.sales.models.order import ErpSalesOrderModel
from core.features.sales.models.order_line import ErpSalesOrderLineModel

__all__ = [
    "ErpSalesOrderLineModel",
    "ErpSalesOrderModel",
]
