# FIN — Chart of accounts gap: sales fulfilment silently breaks for real tenants

**Status:** OPEN — flagged from `feat/HR-AUT-001/Payroll-Batch-Runs-and-Notification-Orchestrator`. Not fixed in that branch (out of scope); fix belongs to the Finance owner.

**Severity:** High for any production/staging tenant. Sales order fulfilment fails with a 404-style `NotFoundError` on the COGS account for every tenant that was not provisioned by the demo seeder.

---

## Finding

Finance's chart of accounts is currently created **only** by the demo seed path:

- `services/core/src/core/seed_demo.py` (`~line 440`) inserts revenue `4000` and COGS `5000` (and the demo tenant's other accounts).

Tenant provisioning, by contrast, seeds **no finance defaults**:

- `services/core/src/core/cli.py` `_seed_tenant` seeds HR defaults + RBAC roles only.
- There is no finance seeder, no `tenant.created` lifecycle handler, and no migration that backfills a default chart for existing tenants.

The payroll/HR module avoided this trap because its reference data and permissions are created per-tenant on provisioning; finance is the one module that assumed seed-demo-only accounts would exist everywhere.

## Evidence

- `services/core/tests/integration/api/sales/test_sales_api.py::TestFulfil::test_fulfil_creates_invoice` fails: `NotFoundError: COGS account '5000' not found`.
- The lookup is in `services/core/src/core/features/finance/service.py` `create_from_order` (`~line 431`), resolving `COGS_ACCOUNT_CODE` (`"5000"` in `services/core/src/core/core/constants.py:118-119`, revenue `"4000"`).
- Because the integration fixtures provision tenants via `X-Tenant-Slug` without the demo chart, the test only passes when the test-catalog happens to include the codes — the failure reproduces against any fixture tenant that lacks them, and by extension any real tenant.

## Impact

- Sales → order → fulfil → inventory-bin update runs, but the COGS journal-entry step throws and the fulfilment fails/rolls back.
- New tenants onboarding through the register/provision flow (not the demo seeder) get a broken sales pipeline out of the box.
- **Payroll mark-paid also depends on the chart (HR-AUT-001, Commit 4):** the accrual JE bridge resolves accounts 5010 / 2010 / 2020 when a run is marked paid. If they are missing the run does **not** fail — the bridge is fail-safe by design — but it records `je_bridge_status = 'pending'`, which cascades to the payroll admin as a "pending accounts setup" indicator until the chart is provisioned. The `pending` state is the **same root cause** as the COGS failure, surfaced on the payroll run instead of a sales 404. Fixing the chart for a tenant (seeder/backfill) clears both symptoms: sales fulfilment resumes and future mark-paid runs land `draft` JEs.

## Suggested fix (Finance owner)

1. **Per-tenant default chart on provisioning** — mirror what HR does: a finance seeder invoked on tenant creation that inserts the default chart (at minimum `4000` Revenue, `5000` COGS) before any sales/user work starts.
2. **Backfill existing tenants** — a migration or CLI backfill that inserts the default chart rows for tenants created before the fix.
3. **Test guard** — tenant-isolation fixtures should assert the default chart exists for a freshly provisioned tenant, so this class of gap is caught at the seams, not in the sales suite.

## Relay text (to Finance owner / Dennis)

> Found a live gap while validating the HR-AUT-001 payroll automation branch: finance's chart of accounts (`4000` Revenue, `5000` COGS) is only created by the demo seeder. Tenant provisioning (`cli._seed_tenant`) seeds HR defaults + RBAC but no finance chart, and there is no migration backfill. Net effect: sales order fulfilment throws `NotFoundError: COGS account '5000' not found` for any tenant that isn't the demo-seeded one. The same gap now also surfaces in payroll (HR-AUT-001 Commit 4): mark-paid drafts the accrual JE against accounts `5010`/`2010`/`2020`, and their absence sets the run's `je_bridge_status` to `pending` instead of crashing — same root cause, second symptom. Please schedule a per-tenant default-chart seeder (mirroring the HR provisioning pattern) plus a backfill for existing tenants; full detail + suggested fix in `docs/backlog/finance-chart-of-accounts-gap.md`. Not touched in our branch.