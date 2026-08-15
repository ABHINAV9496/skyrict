# HR-BE-002 — Close-out

HR + Payroll backend API and business rules: leave ledger, payroll runs, state
machines, RLS isolation, audit + events, and the concurrency hardening that
turned out to be necessary. This document records what was delivered, item by
item, with source/test citations, and the exact verification evidence for the
final gate.

Verification status: **all items closed, all gates green** as of
`e267d3d` (see [Verification gate](#verification-gate)).

---

## The 14 canonical items

| # | Item | Status | Evidence |
|---|------|--------|----------|
| 1 | Pending cancellation emits `hr.leave.cancelled` and removes the request from the pending queue | Done | `test_cancel_from_pending_cancels_without_movement` (`tests/unit/features/test_leave_service.py`); `test_pending_cancel_emits_leave_cancelled` (`tests/unit/features/test_feature_events.py`); `cancel_leave_request` pending branch (`services/core/src/core/features/hr/service.py`) |
| 2 | Repository-level payroll-entry immutability (four scenarios) | Done | `TestRepositoryLevelEntryImmutability` (`tests/integration/api/test_payroll_api.py:319`) — see [Item 2 detail](#item-2---repository-level-entry-immutability-four-cases) |
| 3 | Accrual runs at compute time (per-period, for the whole roster) | Done | `test_concurrent_compute_idempotent` and `test_concurrent_compute_with_approval_no_deadlock` (`tests/integration/api/test_concurrency_atomicity.py`); accrual loop in `compute_run` (`services/core/src/core/features/payroll/service.py:308`) |
| 4 | Adjustments apply as net adjustments to the computed entry | Done | `test_adjustment_is_flat_amount` (`tests/unit/features/test_payroll_compute.py`); adjustment wiring in compute entry assembly |
| 5 | Roster scope: everyone hired by period end, minus terminations (earn through termination date) | Done | `TestRosterScope::test_terminated_mid_period_included_and_others_excluded` (`tests/integration/api/test_payroll_api.py:271`); `list_active_employees` (`services/core/src/core/features/payroll/repository.py:647`) |
| 6 | `skipped_employees` surfaced on the run result (e.g. no active compensation) | Done | `test_employee_without_compensation_is_skipped` (`tests/integration/api/test_payroll_api.py:159`) |
| 7 | Compensation recorded → audit + `hr.compensation.recorded` event | Done | `test_record_compensation_emits_compensation_recorded` (`tests/unit/features/test_feature_events.py`); `test_history_and_active_compensation` (`tests/integration/api/test_payroll_api.py:76`) |
| 8 | Events emitted only after commit; a failed transaction emits nothing | Done | `test_buffered_event_discarded_when_commit_fails` (`tests/integration/api/test_concurrency_atomicity.py`); `test_buffered_events_are_not_published_until_flush` (`tests/unit/features/test_feature_events.py`); drained via true session listeners, `092b55a` |
| 9 | Concurrency guards on run-status transitions and entry writes | Done | `test_recompute_loses_cas_race_raises` (`tests/unit/features/test_payroll_service.py:452`); `test_compute_pay_days_and_amounts` / `test_recompute_is_idempotent` (`tests/integration/api/test_payroll_api.py:130`, `:176`); atomic run-status CAS `dc77e45`, atomic entry-update guard `9cb80d5` |
| 10 | Stale payroll entries cleaned before recompute, only while the run is mutable | Done | guarded `delete_entries_for_run` (`services/core/src/core/features/payroll/repository.py`), `9071545`; `test_direct_delete_allowed_on_computed_run` / `test_direct_delete_blocked_on_approved_run` (`tests/integration/api/test_payroll_api.py:446`, `:467`) |
| 11 | DB-level leave-ledger hardening: append-only movements + non-negative balance | Done | Migration `0009_payroll_movements_triggers.py` (`1345071`); `TestLeaveLedgerTriggers` (`tests/integration/database/test_leave_movement_triggers.py`): negative insert rejected/rolled back, zero allowed, direct update rejected, direct delete rejected (`4cdf622`) |
| 12 | Approval emits the real entry count | Done | `test_approve_emits_real_entry_count` asserting `entry_count == 1` (`tests/unit/features/test_payroll_service.py:479`), `233bda7` |
| 13 | Employee state machine tightened: termination only from `active` | Done | `test_status_transitions_and_termination` (`tests/integration/api/test_hr_api.py:117`); `test_approve_rejected_for_terminated_employee` (`tests/unit/features/test_leave_service.py`), `0757814` |
| 14 | Department update emits changed fields | Done | `test_department_update_emits_changed_fields` (`tests/unit/features/test_feature_events.py`) |

### Item 2 — repository-level entry immutability (four cases)

Canonical four scenarios, all green at the repository layer (direct repo calls,
bypassing the service):

| Case | Test | Guard |
|------|------|-------|
| UPDATE blocked on **approved** run | `test_direct_update_blocked_on_approved_run` (`test_payroll_api.py:372`) | atomic WHERE-guard in `update_entry` (`payroll/repository.py`) |
| UPDATE blocked on **paid** run | `test_direct_update_blocked_on_paid_run` (`test_payroll_api.py:391`) | same guard |
| UPDATE blocked on **voided** run | `test_direct_update_blocked_on_voided_run` (`test_payroll_api.py:412`) | same guard |
| UPDATE allowed on **computed** run | `test_direct_update_allowed_on_computed_run` (`test_payroll_api.py:431`) | same guard, mutable statuses allowed |

Classification (verified with `git log -p`): a select-then-raise backstop
predated these tests (`65249aa`), and the tests (`9545006`) formalized that
coverage. The backstop was then hardened from select-then-raise to an **atomic**
conditional-UPDATE guard (`9cb80d5`) — a real correctness improvement beyond a
pure test gap. Net: **0 code defects** in the four cases; 1 hardening commit
and 4 tests.

Out-of-scope finding from this exercise: the DELETE path had **no** immutability
guard at all — `delete_entries_for_run` would happily drop entries from an
approved/paid/voided run. That was a real correctness gap and is closed by
`9071545` + the two delete tests (`test_payroll_api.py:446`, `:467`).

---

## The stale-balance race — unplanned discovery

Discovered, not designed, and **outside** the 14-item list: two concurrent
approvals on different requests for the same employee could both read the same
pre-approval balance, both pass the negative-balance check, and both write a
materialized `erp_leave_balances` row from their own transaction's view — the
ledger went negative while the materialized balance read `>= 0`, invisible to
`ck_erp_leave_balances_non_negative`.

**Lifecycle**

1. **Discovered** during concurrency hardening review (item 9) — initial
   reproduction: `test_concurrent_approve_cross_requests_invariant`, shipped
   `xfail` (`79e43b7`).
2. **Tracked** in this doc's predecessor, §4.3 item 5 of
   `docs/modules/hr-payroll.md`, as a known, unresolved, tracked defect — not an
   accepted tradeoff.
3. **Fixed** — row-level locking, see below.
4. **Closed** — §4.3 rewritten to RESOLVED (`e267d3d`); the `xfail` is a
   deterministic pass; stress/deadlock/first-grant regressions added.

**Fix mechanism.** Every balance-mutating path takes a row lock on
`erp_leave_balances (tenant_id, employee_id, leave_type)` before reading or
rechecking the balance:

- `HrRepository.lock_leave_balance` (`hr/repository.py:502`) **seeds** the row
  (`INSERT ... ON CONFLICT DO NOTHING` on `uq_erp_leave_balances_employee_type`,
  balance 0) then `SELECT ... FOR UPDATE`. Seeding is required: FOR UPDATE on a
  missing row locks nothing, and the row would otherwise only be created by
  `upsert_balance`.
- After the lock, the service **re-probes with a fresh recompute** — never the
  pre-lock value — so the `>= 0` check runs against the serialized state
  (`hr/repository.py:518`, re-probe used by approve/accrual).
- `approve_leave_request` locks before its §4.2 check (`hr/service.py:521`);
  cancellation of an approved request locks before the reversal
  (`hr/service.py:663`); the accrual path locks in `accrue_leave_movement`
  (`hr/repository.py:518`).
- **Deadlock ordering.** Multi-row callers acquire locks in a stable
  deterministic order. `compute_run`'s accrual loop iterates
  `list_active_employees`, which sorts by `employee_number`
  (`payroll/repository.py:647`). The LOCK-ORDERING CONTRACT is documented at the
  call site (`payroll/service.py:308`) and on `lock_leave_balance`
  (`hr/repository.py:518`). No code change was needed for ordering — the roster
  query was already deterministic; the contract is now load-bearing and
  documented.

**Regression coverage** (`tests/integration/api/test_concurrency_atomicity.py`):

- `test_concurrent_approve_cross_requests_invariant` — passes deterministically,
  no longer `xfail`.
- `test_concurrent_approve_cross_requests_stress_balance_exact` — 10 concurrent
  approvals; materialized balance == ledger == 0, movements == approvals.
- `test_concurrent_compute_with_approval_no_deadlock` — compute racing an
  approval; run computed, grants + approval movement settle, materialized ==
  ledger.
- `test_concurrent_first_grant_single_movement` — two concurrent first-grant
  accruals produce exactly one grant movement; proves the post-lock re-probe.

Related anomalies logged (not fixed here, out of scope): migration 0009's
`erp_leave_movements_guard_negative` trigger applies to **all** leave types, so
a *serial* negative non-accrual approval already 500s at INSERT while the
service allows it by design — a pre-existing inconsistency to be reconciled in a
follow-up.

---

## Verification gate

All commands run at `services/core` (or repo root where noted), live Postgres on
`localhost:5433`.

| Check | Result |
|-------|--------|
| `pytest tests/ -q` | **361 passed, 0 failed, 0 xfail, 0 xpass** (baseline 355 + 1 xpassed) |
| `ruff check services/core/` | 12 findings, all pre-existing, none in changed files |
| `ruff format --check services/core/` | 11 pre-existing files unformatted, none in changed files |
| `mypy services/core/src/` | 6 errors, all pre-existing baseline, none new |
| `import-linter lint --config services/core/import-linter.toml` | 4 contracts kept, 0 broken |
| `pytest tests/integration/database/` | 54 passed, incl. `test_core_migration_chain_round_trips_up_down_up` (upgrade head → downgrade base → upgrade head against a scratch live DB) and all 5 trigger tests |
| Repeated concurrency runs | stress + deadlock tests: **5/5**; first-grant test: **5/5** |

---

## Commit range

`git log --oneline 0f2021e..HEAD` (run live — snapshot below captured at
`9054673`, 30 commits):

```
9054673 docs(core): [HR-BE-002] finalize close-out commit range with this commit included
aab0b07 docs(core): [HR-BE-002] add close-out record with item citations, race lifecycle, and gate evidence
e267d3d docs(core): [HR-BE-002] mark leave-approval atomicity race RESOLVED in hr-payroll.md 4.3
7a6f439 test(core): [HR-BE-002] add lock_leave_balance no-op to unit-test repository doubles
0c57f7f test(core): [HR-BE-002] stale-balance xfail to deterministic pass + stress/deadlock/first-grant/delete-guard tests
9071545 fix(core): [HR-BE-002] guard delete_entries_for_run against immutable runs
460e9ec fix(core): [HR-BE-002] serialize employee balance mutations with row-level locking
7ff5f70 style(core): [HR-BE-002] lint/format hygiene for this session's changes
092b55a fix(core): [HR-BE-002] drain after-commit events via true session listeners, not an explicit post-commit call
9cb80d5 fix(core): [HR-BE-002] make entry updates atomically guarded instead of select-then-raise
dc77e45 fix(core): [HR-BE-002] make compute persist via atomic run-status CAS
4cdf622 test(core): [HR-BE-002] DB behavioral tests for the leave-ledger triggers
1345071 feat(core): [HR-BE-002] migration 0009 — DB-level leave-ledger hardening (append-only + non-negative)
0757814 fix(core): [HR-BE-002] align employee state machine with docs — termination only from active
233bda7 fix(core): [HR-BE-002] emit the real entry count on payroll-run approval
79e43b7 docs(core): [HR-BE-002] document the unresolved cross-request stale-balance race and cite it as the xfail reason
9545006 test(core): [HR-BE-002] add repository-level entry immutability test
004f7e3 test(core): [HR-BE-002] add roster-scope integration test for terminated/pre-hire employees
65249aa feat(core): [HR-BE-002] land gap-audit working tree — 16-row reconstruction + migration 0008
5213dd4 feat(core): close HR-BE-002 gap-audit findings + DoD tests + migration 0007
f666c9f feat(core): checkpoint - HR/payroll API routers, schemas, service wiring (pre gap-audit baseline)
8bfcc08 feat(core): implement HR + payroll repositories (leave ledger, runs, entries, settings)
aa3f4f1 feat(core): seed core_roles system roles per tenant + wire into seed CLI
f5e2610 feat(identity): migration 0015 - mirror ERP payroll + HR approve permissions, grant per design doc
081e0ca test(core): integration tests for audit hash chain and ERP sequences
6a04339 feat(core): add audit events catalog, audit service, and ERP sequence service
6718ec0 feat(core): add audit and ERP sequence ports and repositories
c09f43e feat(core): add core audit log and ERP sequence ORM models + domain entities
c320255 feat(core): add ERP HR and Payroll permission keys to core catalog
1de8cc9 feat(core): migration 0006 - ERP sequences + core audit hash chain, seeds ERP permission keys
```
