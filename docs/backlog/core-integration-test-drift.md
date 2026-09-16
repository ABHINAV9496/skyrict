# Core - pre-existing integration-test drift (tech-debt log)

Logged during the SKY-70 semantic search gate (branch `feat/SKY-70-semantic-inventory-search`).
Scope decision (user-approved): **leave as tech-debt; do not fix under SKY-70.**

Status: **closed**. Every failure below reproduced at the SKY-70 split base
(`08caa27` / `a12e1d7`) on a freshly recreated `skyrict_core_verify` database.
All 11 have since been resolved by commits in the `main`/HEAD lineage; none
reproduces on this branch at a freshly recreated `skyrict_core_verify`.

Verification evidence (branch `fix/BUG-CORE-001/...`, HEAD referenced by the
commits below; database + unit jobs run against a DROP/CREATE'd
`skyrict_core_verify` on `localhost:5433`):

- `services/core/tests/integration/database/` - **177 passed, 0 failed**
- `services/core/tests/unit/` - **1345 passed, 0 failed**

## Root cause A - stale `annual` accrual expectations (9 tests)

Commit `ff822f8` "feat(leave): replace annual with policy-driven casual+sick
(Leave Type Rework)" replaced the legacy `annual` accrual with
policy-driven `casual` + `sick`. The 9 integration tests below asserted an
`annual` balance that can never exist after the rework:

| Test                                                                                                                | Failure                                            |
| ------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| `test_hr_api.py::TestLeaveLifecycle::test_balance_accrues_on_hire_and_approval_deducts`                             | `KeyError: 'annual'` from `GET /hr/leave/balances` |
| `test_hr_api.py::TestLeaveLifecycle::test_approve_beyond_balance_is_rejected`                                       | expects `annual` balance to exist                  |
| `test_hr_api.py::TestLeaveLifecycle::test_cancel_approved_request_refunds_balance`                                  | expects `annual` balance to exist                  |
| `test_concurrency_atomicity.py::TestConcurrentApprove::test_concurrent_approve_single_request`                      | approve `422` for `annual` leave request           |
| `test_concurrency_atomicity.py::TestConcurrentApprove::test_concurrent_approve_cross_requests_invariant`            | same                                               |
| `test_concurrency_atomicity.py::TestConcurrentApprove::test_concurrent_approve_cross_requests_stress_balance_exact` | same                                               |
| `test_concurrency_atomicity.py::TestConcurrentCompute::test_concurrent_compute_with_approval_no_deadlock`           | same                                               |
| `test_concurrency_atomicity.py::TestConcurrentAccrual::test_concurrent_first_grant_single_movement`                 | same                                               |
| `test_concurrency_atomicity.py::TestNoEventOnFailedTransaction::test_approve_beyond_balance_no_event`               | same                                               |

Resolution: switched to `casual`/`sick` in `8102cf7f` ("test: align leave
lifecycle/concurrency tests with casual leave bucket post-rework"), matching
the rework's model and its updated unit tests.

## Root cause B - sales fulfil needs a seeded COGS account (1 test)

| Test                                                               | Failure                             |
| ------------------------------------------------------------------ | ----------------------------------- |
| `sales/test_sales_api.py::TestFulfil::test_fulfil_creates_invoice` | `404 COGS account '5000' not found` |

Resolution: the fulfil test's own setup seeds the COGS (`5000`), revenue, and
inventory chart-of-accounts rows (`test_sales_api.py` tenant-finance setup).

## Pre-existing (already tracked) - unrelated

| Test                                                                                       | Notes                                                                           |
| ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| `unit/features/test_ai_hr_anomaly_service.py::test_team_size_gate_passes_for_four_members` | Known pre-existing model-eval behavioral failure at the SKY-70 base; verified unrelated to SKY-70. |

Resolution: made date-deterministic by `0c05386b` + `951d466e`.

## Residual semantic drift - DB-layer tests (aligned by BUG-CORE-001)

The API-layer failures above were already fixed before this ticket. Two
DB-layer integration test files still carried pre-rework catalogue semantics
(asserts/seed data referencing `annual`, and `sick` treated as non-accrual
even though the rework made it an accrual type). These were not failing, but
constituted a latent false-failure signal for any legitimate future catalog
change, so they were aligned with the current model:

- `test_hr_payroll.py` - seeds `casual` + `sick` per tenant; catalogue
  assertion now `["casual", "sick"]`; FK/constraint tests use `casual`.
- `test_leave_movement_triggers.py` - seeds `casual`(accrual) + `sick`(accrual)
  + `unpaid`(ledger-only); the non-accrual guard-negative test now exercises
  the real ledger-only `unpaid` type; `ref_type`/defaults use `casual`.

Resolution: `fbf61ce9` ("test(hr): align integration DB tests with
post-rework casual/sick leave catalog").