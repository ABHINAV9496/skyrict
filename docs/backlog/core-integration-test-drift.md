# Core — pre-existing integration-test drift (tech-debt log)

Logged during the SKY-70 semantic search gate (branch `feat/SKY-70-semantic-inventory-search`).
Scope decision (user-approved): **leave as tech-debt; do not fix under SKY-70.**

Status: **open**. Every failure below reproduces at the SKY-70 split base
(`08caa27` / `a12e1d7`) on a freshly recreated `skyrict_core_verify` database,
with zero SKY-70 involvement. Full suite: 815 passed, 11 failed; the 11th
(`test_team_size_gate_passes_for_four_members`, model-eval anomaly) is a
separate, already-followed pre-existing failure.

## Root cause A — stale `annual` accrual expectations (9 tests)

Commit `ff822f8` "feat(leave): replace annual with policy-driven casual+sick
(Leave Type Rework)" replaced the legacy `annual` accrual with
policy-driven `casual` + `sick` (`hr/service.py::_accrue_annual` and
`accrue()` handle only `casual`/`sick`; a people-resource with only
`annual` never materializes a balance). The integration tests below were
never updated, so they assert an `annual` balance that can never exist:

| Test | Failure |
|------|---------|
| `test_hr_api.py::TestLeaveLifecycle::test_balance_accrues_on_hire_and_approval_deducts` | `KeyError: 'annual'` from `GET /hr/leave/balances` |
| `test_hr_api.py::TestLeaveLifecycle::test_approve_beyond_balance_is_rejected` | expects `annual` balance to exist |
| `test_hr_api.py::TestLeaveLifecycle::test_cancel_approved_request_refunds_balance` | expects `annual` balance to exist |
| `test_concurrency_atomicity.py::TestConcurrentApprove::test_concurrent_approve_single_request` | approve `422` for `annual` leave request |
| `test_concurrency_atomicity.py::TestConcurrentApprove::test_concurrent_approve_cross_requests_invariant` | same |
| `test_concurrency_atomicity.py::TestConcurrentApprove::test_concurrent_approve_cross_requests_stress_balance_exact` | same |
| `test_concurrency_atomicity.py::TestConcurrentCompute::test_concurrent_compute_with_approval_no_deadlock` | same |
| `test_concurrency_atomicity.py::TestConcurrentAccrual::test_concurrent_first_grant_single_movement` | same |
| `test_concurrency_atomicity.py::TestNoEventOnFailedTransaction::test_approve_beyond_balance_no_event` | same |

Fix direction (whenever resourced): switch these to `casual`/`sick` (or a
leave-type the tenant policy accrues), aligning with the rework's model and
its updated unit tests (`test_leave_service.py::test_list_accrual_leave_types_returns_only_accrual_types`
asserts `["casual", "sick"]`).

## Root cause B — sales fulfil needs a seeded COGS account (1 test)

| Test | Failure |
|------|---------|
| `sales/test_sales_api.py::TestFulfil::test_fulfil_creates_invoice` | `404 COGS account '5000' not found` |

Fulfilment creates an invoice whose COGS journal-entry references chart-of-accounts
code `5000`; no finance seed currently creates that account, so the request 404s.
Fix direction: add `5000` (Cost of Goods Sold) to the tenant finance
chart-of-accounts seed used by integration tests (or the fulfil test's own setup).

## Pre-existing (already tracked) — unrelated

| Test | Notes |
|------|-------|
| `unit/features/test_ai_hr_anomaly_service.py::test_team_size_gate_passes_for_four_members` | Known pre-existing model-eval behavioral failure; verified unrelated to SKY-70. |