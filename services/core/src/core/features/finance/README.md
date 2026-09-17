# Finance Module

Chart of accounts, general ledger, invoicing, payments, fixed-asset depreciation,
expense policy + claims, budgets, and compliance reminders. Lives in
`services/core/src/core/features/finance/` and is mounted at `/api/v1/finance*`.

## Architecture

```
router.py / automation*.py / payment_match.py      HTTP layer (thin)
        │  Depends(require_permission<erp.finance.*>)  + Depends(get_finance_*_service)
        ▼
service.py / automation*.py / payment_match.py     use-cases (Money, TenantContext)
        ▼
repository.py (Repository) / ports.py (Protocols)  persistence (RLS-pinned via after_begin)
        ▼
finance/models/*.py                                tables (all tenant-scoped)
```

- Every endpoint is guarded by a `erp.finance.*` / core permission key; nothing in
  this module is reachable without a granted key (see `core/core/permissions.py`,
  currently 60+ keys including `erp.budget.*`, `erp.asset.*`, `erp.expense.*`,
  `erp.compliance.*`).
- Money never leaves `core.domain` as a float: `Money` (Decimal + currency) is the
  only amount type across service and schema layers.
- All rows are tenant-scoped; RLS is enforced by the shared
  `current_tenant_id()` policy (see `services/core/README.md`).

## Chart of Accounts

The chart is the spine of this module.

| Code | Name                  | Type     |
| ---- | --------------------- | -------- |
| 1100 | Accounts Receivable   | asset    |
| 1200 | Cash                  | asset    |
| 1300 | Inventory Asset       | asset    |
| 2010 | Accrued Salaries      | liability|
| 2020 | Tax Payable           | liability|
| 2110 | Accounts Payable      | liability|
| 4000 | Sales Revenue         | revenue  |
| 5000 | Cost of Goods Sold    | expense  |
| 5010 | Salaries Expense      | expense  |

Provisioning is the single source of truth `core.seed.DEFAULT_CHART_ACCOUNTS`
(the frozen migration snapshot in `alembic/versions/0063_..._backfill.py` must be
kept in sync when it changes):

- **New tenants** get all 9 codes via `seed_tenant_finance_defaults()` (called by
  `core cli seed`, `seed_demo`, and the onboarding path).
- **Pre-existing tenants** were reconciled by migration 0063 (a cross-join
  `ON CONFLICT (tenant_id, code) DO NOTHING` backfill).
- Sales fulfilment (`post_cogs_for_order`, `create_from_order`) resolves the COGS
  (`5000`) and revenue (`4000`) codes from this chart - a tenant without them
  cannot book an order, which is why provisioning is mandatory.

## Key Flows

- **Journal entry lifecycle**: `POST /finance/journal-entries` (draft) →
  `POST /finance/journal-entries/{id}/post` (posted) → `void` (reverse entry).
  `post_journal_entry` posts and linearizes the ledger; `void` reverses and voids.
- **Invoicing**: create → issue (locks the invoice) → approve → apply_payment →
  void. Approval routes through the shared approval-workflow engine when the
  amount exceeds the tenant's approval threshold.
- **Depreciation**: `POST /finance/depreciation/run` books a period's
  depreciation for every owned asset; `(tenant_id, asset_id, period)` uniqueness
  makes each period exactly-once (idempotent re-runs).
- **Expense policy**: per-category policies with limits; claim submission is
  evaluated against the policy and records violations. Approval is AI-routed
  for auto-approved categories.
- **Budgets**: plan fiscal-year spend per account; `BudgetOverrunWorker`
  (lifespan background loop, or `core budget-overrun run`) scans posted activity
  and emits `budget_overrun:*` notifications when a line exceeds its plan.
- **Payment matching**: `payment_match.py` links invoices to received payments;
  wave-3 adds suggested matches for manual review.
- **Compliance calendar**: recurring compliance items; a reminder worker drains
  upcoming items (`core compliance-reminders run`).

## Workers (lifespan-managed)

Enabled by env var, disabled under TEST so integration tests drive them directly:

| Worker              | Env flag                                  | Manual trigger                |
| ------------------- | ----------------------------------------- | ----------------------------- |
| Budget overrun scan | `CORE_FINANCE_BUDGET_OVERRUN_WORKER_ENABLED` | `core budget-overrun run` |

Depreciation runs on demand (`POST /finance/depreciation/run`); compliance
reminders emit on demand (per-item, after completing an item). Report snapshot
retention is a separate core worker (`CORE_REPORTING_RETENTION_ENABLED`,
`core retention run`).

## Extending the Module

1. Add the table + model in `finance/models/` with a `tenant_id` composite FK
   (see `core/models/tenant.py` conventions) and an Alembic migration.
2. Add read/write/approve permission keys in `core/core/permissions.py` and run
   the migration to seed them.
3. Add repository methods to `repository.py`; keep transaction/RLS semantics in
   the service layer.
4. Add an endpoint in the feature's `router` and ALWAYS guard it with the new
   permission key - do not reuse `erp.finance.write` for a narrower capability.
5. Add the keys to `seed_core_roles_for_tenant` (organization_admin) so existing
   tenants get them via the RBAC sync.

## Testing

- Unit (no DB): `uv run pytest services/core/tests/unit/features/finance/ -v`
- Integration (real Postgres): `uv run pytest services/core/tests/integration/database/test_finance_chart_defaults.py services/core/tests/integration/api/sales/test_sales_api.py -v`
- Migration chain: `uv run pytest services/core/tests/integration/database/test_migration_roundtrip.py -v`
  (asserts 0062 creates the wave-4 tables + 0063 backfills the 9-code chart for
  pre-existing tenants).