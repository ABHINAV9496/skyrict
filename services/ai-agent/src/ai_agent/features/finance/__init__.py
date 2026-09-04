"""Finance Assistant agent (registered in ``agent_registry``).

Reads invoices, P&L, AR-aging, and the chart of accounts through core's
``/api/v1/finance`` endpoints. Every read forwards the caller's JWT + tenant
slug, so core enforces ``erp.finance.read`` + tenant isolation - the assistant
sees exactly the finance data the acting user may view in the UI. Money is
Decimal throughout; no float money ever leaves this module.
"""
