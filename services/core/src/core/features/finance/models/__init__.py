"""Finance ORM models - one file per ``erp_*`` table (FIN-DATA-001).

Feature models are NOT re-exported from ``core.models``: importing that
package from ``core.features`` would violate the import-linter layering
contract, so the migration runner imports these models directly.
"""

from core.features.finance.models.ai_finance_anomaly import AiFinanceAnomalyModel
from core.features.finance.models.ai_finance_quality_score import AiFinanceQualityScoreModel
from core.features.finance.models.ai_finance_suggestion import AiFinanceSuggestionModel
from core.features.finance.models.budget import ErpBudgetLineModel, ErpBudgetModel
from core.features.finance.models.budget_draft import ErpBudgetDraftModel
from core.features.finance.models.budget_draft_line import ErpBudgetDraftLineModel
from core.features.finance.models.chart_of_account import ErpChartOfAccountModel
from core.features.finance.models.compliance_item import ErpComplianceItemModel
from core.features.finance.models.depreciation_entry import ErpDepreciationEntryModel
from core.features.finance.models.exchange_rate import ErpExchangeRateModel
from core.features.finance.models.expense_claim import ErpExpenseClaimModel
from core.features.finance.models.expense_policy import ErpExpensePolicyModel
from core.features.finance.models.expense_policy_violation import ErpExpensePolicyViolationModel
from core.features.finance.models.fiscal_period import ErpFiscalPeriodModel
from core.features.finance.models.fixed_asset import ErpFixedAssetModel
from core.features.finance.models.invoice import ErpInvoiceModel
from core.features.finance.models.invoice_line import ErpInvoiceLineModel
from core.features.finance.models.journal_entry import ErpJournalEntryModel
from core.features.finance.models.journal_line import ErpJournalLineModel
from core.features.finance.models.journal_template import ErpJournalTemplateModel
from core.features.finance.models.payment import ErpPaymentModel
from core.features.finance.models.tenant_setting import ErpTenantSettingModel

__all__ = [
    "AiFinanceAnomalyModel",
    "AiFinanceQualityScoreModel",
    "AiFinanceSuggestionModel",
    "ErpBudgetDraftLineModel",
    "ErpBudgetDraftModel",
    "ErpBudgetLineModel",
    "ErpBudgetModel",
    "ErpChartOfAccountModel",
    "ErpComplianceItemModel",
    "ErpDepreciationEntryModel",
    "ErpExchangeRateModel",
    "ErpExpenseClaimModel",
    "ErpExpensePolicyModel",
    "ErpExpensePolicyViolationModel",
    "ErpFiscalPeriodModel",
    "ErpFixedAssetModel",
    "ErpInvoiceLineModel",
    "ErpInvoiceModel",
    "ErpJournalEntryModel",
    "ErpJournalLineModel",
    "ErpJournalTemplateModel",
    "ErpPaymentModel",
    "ErpTenantSettingModel",
]
