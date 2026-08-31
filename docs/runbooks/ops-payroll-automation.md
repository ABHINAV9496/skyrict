# Runbook: Payroll Automation — Batch Runs, Schedules, Notifications & Accrual JE Bridge

Operational runbook for the HR-AUT-001 payroll automation feature suite
(batch processing, recurring submission scheduler, notification digests and the
Commit-4 payslip surface + payroll→Finance accrual JE bridge). This is the
Definition-of-Done ops artifact for ticket **HR-AUT-001**.

Design/spec references:
[`docs/modules/hr-payroll.md`](../modules/hr-payroll.md) (Rule 10 §4.10, run
lifecycle §5.3, API reference §7) and
[`docs/modules/skyrict-ai/hr-payroll-ai-features.md`](../modules/skyrict-ai/hr-payroll-ai-features.md)
(§15).

---

## Operational overview

Per tenant, the pipeline is: a payroll run is **enqueued** (manually via API, or
automatically by a due **schedule**) → the in-process **worker** claims the batch
and computes each employee's pay with a durable commit per item → the batch
reaches a terminal state → **notifications** fan out (payslip-ready per
employee + admin digest) → marking the run **paid** drafts the salary-accrual
journal entry through the Finance seam.

The background worker runs inside the `services/core` process (started in the
API lifespan; claims one eligible batch per tick via `FOR UPDATE SKIP LOCKED`,
`items_per_tick=10`, `poll_seconds=0.25`). `POST /api/v1/ai/payroll/tick`
drives the same `process_once` path deterministically and is the canonical
manual/CI operator control.

### State machines

| Object | States |
|---|---|
| Batch (`ai_payroll_batch_runs`) | `queued` → `processing` → `completed` \| `failed` \| `aborted` |
| Item (`ai_payroll_batch_items`) | `pending` → `processing` → `done` \| `failed` |
| Payroll run (`erp_payroll_runs`) | `draft` → `computed` → `approved` → `paid`; `void` from `draft`/`computed`/`approved` |

### Key endpoints (full reference in `hr-payroll.md` §7)

| Method | Path | Permission | Purpose |
|---|---|---|---|
| POST | `/api/v1/ai/payroll/batches` | `erp.payroll.ai.run` | Enqueue a run (`run_id`, `dry_run?`); idempotent per run |
| GET | `/api/v1/ai/payroll/batches?status=` | `erp.payroll.ai.read` | Queue view |
| GET | `/api/v1/ai/payroll/batches/{id}` | `erp.payroll.ai.read` | Batch detail with `preflight` + `totals` |
| POST | `/api/v1/ai/payroll/tick` | `erp.payroll.ai.run` | Advance processing + fire due schedules; returns `items_processed`, `status_changed`, `schedules_fired` |
| GET/POST/PATCH/DELETE | `/api/v1/ai/payroll/schedules[...]` | `read` / `run` | Schedule CRUD (`name?`, `cron_expression`, `enabled`) |
| GET | `/api/v1/ai/payroll/notifications` | `erp.payroll.ai.read` | Inbox; filters `event_type`, `after`/`before` |
| GET/PUT | `/api/v1/ai/payroll/notifications/preferences` | `erp.payroll.ai.notify` | Per-user `in_app_on`, `email_on` (self-scoped) |
| GET | `/api/v1/payroll/runs/{id}` | `erp.payroll.read` | Run detail incl. `je_bridge_status` |
| GET | `/api/v1/payroll/runs/{id}/payslips` | `erp.payroll.read` | Per-employee gross/deductions/net; `[]` while `draft` |
| POST | `/api/v1/payroll/runs/{id}/pay` | `erp.payroll.approve` | `approved→paid`; triggers the JE bridge (docs call this "mark-paid") |
| PUT | `/api/v1/payroll/settings` | `erp.payroll.write` | `ai_automation_enabled`, `je_bridge_enabled` flags |

### Preflight checks (run at enqueue; evidence persisted in batch JSONB)

| Check | Block or warn | Detail shown when it trips |
|---|---|---|
| `settings` | **block** | no payroll settings row for tenant |
| `automation_enabled` | **block** | `ai_automation_enabled` is off |
| `run` | **block** | run is not `draft`/`computed` |
| `period` | **block** | another run already covers this period |
| `roster` | **block** | no active employees for the period |
| `banking` | warn | roster employee(s) missing bank details |
| `benefit_elections` | warn | employee(s) with no enrolled benefit election |
| `termination` | warn | active employee flagged with a termination date |

A **block** aborts the batch immediately (`status=aborted`, zero items) —
re-enqueueing after fixing the block **re-arms the same batch row** (fresh
preflight + totals). **Warnings** never abort; they are recorded for the
operator.

### Notifications

`payslip_ready` (per employee) and `payroll_batch_digest` (admins) are composed
**post-commit** when a batch reaches a terminal state; composition is idempotent
(`dedupe_key` UNIQUE), and a fan-out failure never fails the processing tick
(it logs and rolls back the notification rows only). Delivery pivots on
per-user `ai_payroll_notification_prefs` (`in_app_on` default true, `email_on`
default false).

### Accrual JE bridge (Rule 10, `je_bridge_enabled` + `total_gross > 0`)

On `mark_paid` (`approved→paid`): DR `5010` Salaries Expense = gross; CR `2010`
Accrued Salaries = net; CR `2020` Salary Deductions Payable = `gross − net`
**only when deductions > 0**. Source `payroll`, `source_ref=str(run_id)`,
status `DRAFT`, dated at `paid_at`. Idempotent via
`UNIQUE(tenant_id, source, source_ref)`.

| Outcome | `je_bridge_status` on the run |
|---|---|
| Chart missing 5010/2010/2020 | `pending` |
| Entry created or already booked | `draft` |
| Anything else (or flag off / zero gross) | `none` |

The bridge **never fails `/pay` (docs "mark-paid")** — the run records the truth instead. Runs
voided after payment leave the DRAFT entry for the Finance owner.

---

## Severity

Baseline **P3**: payroll is scheduled, tenant-scoped, and finance-adjacent — a
stuck batch or missing notification is a process impact, not a service outage.

- Escalate **P2** if a tenant's period-end batch cannot complete across two or
  more consecutive payoff cycles, or if schedules silently stop firing for more
  than a full cycle.
- Escalate **P1** if the pipeline is down for **all** tenants (this is the
  worker/lifespan being unavailable — i.e. the `services/core` process), per the
  existing core/identity outage runbooks.

## Symptoms

- A period-end batch stays in `queued` or `processing` well past its post time.
- A batch ends `failed` or `aborted`, or individual items are `failed`.
- Payslip-ready / batch-digest notifications never arrive in the inbox or email,
  while the batch itself completed.
- A paid run shows `je_bridge_status = pending` (no DRAFT accrual entry in
  Finance).
- A schedule's `next_run_at` passes without firing (`schedules_fired` stays 0 in
  tick responses; `last_fired_at` stale).
- `POST /ai/payroll/tick` returns `items_processed = 0` unexpectedly.

## Impact

Payroll admins cannot confirm a run completed and payslips are not "ready",
employees do not receive payslip-ready/digest notifications, and Finance never
receives the monthly salary-accrual DRAFT — forcing manual re-run/reconciliation
at period close. Aggregated, delayed-period close and unreconciled accruals.

## Diagnosis

Work from the outside in: **API projection → audit/worker logs → database rows**.
All paths below assume operator has `erp.payroll.ai.read` + `erp.payroll.read` +
`erp.payroll.approve` (or run the probes via a support `organization_admin`).

1. **Batch state.** `GET /api/v1/ai/payroll/batches?status=` for the tenant, then
   `GET /api/v1/ai/payroll/batches/{id}`. Inspect `status`, `preflight.blocks`,
   `preflight.warnings`, `totals`, `claimed_by`, `started_at`/`finished_at`.
2. **Run state.** `GET /api/v1/payroll/runs/{id}` — `status` must be `draft`/
   `computed` for a batch to run; note `je_bridge_status`.
3. **Settings.** `GET /api/v1/payroll/settings` — `ai_automation_enabled` and
   `je_bridge_enabled` must be true for their respective flows.
4. **Worker liveness.** Confirm the `services/core` process is healthy. A dead
   worker means the queue drains only via a manual `POST /tick`.
5. **Logs.** `services/core` logs: `payroll.automation.worker.tick`,
   `payroll.automation.worker.tick_failed`, `enqueued payroll automation batch`,
   `aborted payroll automation batch … blocked by <checks>`, and the audit
   events `payroll.run.*`.

Per-scenario probes:

| Scenario → likely cause | Probe |
|---|---|
| **Batch stuck `queued`/`processing`** — worker not claiming | `SELECT status, claimed_by, started_at FROM ai_payroll_batch_runs WHERE tenant_id=<t> AND status IN ('queued','processing');` then confirm worker process/lifespan and advance with `POST /tick`; a `claimed_by` never finishing implies a crashed worker mid-item |
| **Batch `failed` / items `failed`** — compute error on an employee | `SELECT employee_id, status, error FROM ai_payroll_batch_items WHERE batch_id=<b> AND status='failed';` read the persisted item error and reconcile against `hr-payroll.md` error cases |
| **Batch `aborted`** — preflight block | Batch detail `preflight.blocks` (settings / automation_enabled / run / period / roster). Check `erp_payroll_runs.status`, `erp_payroll_settings`, `erp_employees` active roster, and the overlapping-run query `find_overlapping_run` |
| **No notifications despite `completed`** — fan-out gap | `SELECT event_type, recipient_user_id, subject, dedupe_key FROM ai_payroll_notifications WHERE tenant_id=<t> AND run_id=<r>;` (or inbox API) then `SELECT * FROM ai_payroll_notification_prefs WHERE user_id=<u>;` for `in_app_on`/`email_on` |
| **`je_bridge_status=pending`** — chart gap | `SELECT code, name FROM erp_chart_of_accounts WHERE tenant_id=<t> AND code IN ('5010','2010','2020');` missing code(s) = the documented chart-of-accounts gap (backlog `finance-chart-of-accounts-gap.md`) |
| **Schedule not firing** | `SELECT cron_expression, enabled, last_fired_at, next_run_at FROM ai_payroll_schedules WHERE tenant_id=<t>;` then `POST /tick` → `schedules_fired`; confirm worker ticking and the run's period doesn't conflict (`payroll-period-conflict` aborts the ensuing batch) |

## Mitigation

Immediate operator action to restore the period-end:

1. **Confirm/repair preflight**: enable `ai_automation_enabled` (and
   `je_bridge_enabled` for the bridge) in `PUT /api/v1/payroll/settings`; if the
   run left `draft`/`computed` state or the period was won by a stale run, void
   the winner (`POST /payroll/runs/{id}/void`, `reason` required) then
   re-enqueue.
2. **Drive the queue by hand**: `POST /api/v1/ai/payroll/tick` repeatedly until
   `items_processed = 0` — deterministic, observable progress while a worker
   issue is being fixed.
3. **Fish the worker**: if a tick never progresses (`claimed_by` set, items
   `processing`), restart `services/core`. The worker resumes `queued` and
   in-flight `processing` batches (each item is a durable checkpoint, so at most
   one item is re-done); **`aborted` batches are never auto-reclaimed** — fix the
   preflight block and re-enqueue. A `failed` item cannot self-heal — re-run the
   payroll compute (`POST /payroll/runs/{id}/compute`) and re-enqueue.
4. **Bridge**: for `pending`, book the missing chart codes (5010/2010/2020) via
   the Finance chart, then `POST /payroll/runs/{id}/pay` again — the unique constraint makes the
   DRAFT idempotent; do not hand-post a parallel entry. For `draft`, confirm the
   DRAFT (`source='payroll'`) exists in
   `erp_journal_entries` / `erp_journal_lines` before releasing to Finance.
5. **Notifications**: fix delivery prefs (`PUT .../notifications/preferences`),
   then re-drive the batch to a terminal state to re-trigger the post-commit
   fan-out (dedupe prevents duplicates). If records are present but email is
   missing, check the mail relay (SMTP/`email_on`).

## Recovery

- Re-enqueueing an **aborted** batch re-arms the same row only after the block
  is fixed; the operator must re-order operations so `settings`/`run`/`period`/
  `roster` pass **before** re-enqueueing.
- Confirm end-state per run: `erp_payroll_runs.status = paid`,
  `je_bridge_status in ('draft','pending')`, the accrual DRAFT present in
  Finance (`erp_journal_entries.source='payroll'`), and the notification inbox
  shows `payslip_ready`/`payroll_batch_digest` for the run.
- Payroll runs voided after payment leave the accrual DRAFT for the Finance
  owner (per Rule 10) — coordinate rather than deleting.

## Prevention

- **Observability**: alert on (a) batch `queued`/`processing` older than one
  payoff window, (b) `tick_failed` logs, (c) a run `paid` with
  `je_bridge_status=pending`, (d) schedule `next_run_at` in the past with
  `enabled=true`. Link alerts to this runbook per
  [`docs/runbooks/README.md`](./README.md).
- **Chart-of-accounts**: run the §"Diagnosis / `pending`" probe before each
  period-end once the gap backlog item is closed; the bridge degrades to
  `pending` (not silent failure), so treat pending runs as a to-do, not a
  mystery.
- **Automation flag discipline**: `ai_automation_enabled` is the master switch;
  toggling it affects every tenant batch, so change it only in a scheduled
  window and immediately observe the next enqueue.
- **Schedule hygiene**: keep cron expressions in the tenant's intended TZ, and
  remember a due schedule creates a run that can itself hit
  `payroll-period-conflict` — a stale previous-period run blocks the next one.

## References

- `docs/modules/hr-payroll.md` — §4.10 (Rule 10 final), §5.3 (run lifecycle),
  §7 (API reference incl. automation + error cases), §9 (test strategy)
- `docs/modules/skyrict-ai/hr-payroll-ai-features.md` — §15 HR-AUT-001
  (deliverables, permissions, data model, §15.6 FIN-AI-001 seam)
- `docs/backlog/finance-chart-of-accounts-gap.md` — missing 5010/2010/2020 → `pending`
- Code: `services/core/src/core/features/payroll_automation/` (worker, service,
  preflight, schedules, notifications), `features/finance/ports.py` +
  `service.py` (`create_payroll_accrual_draft`), `api/deps.py`
  (`get_payroll_service` — worker/scheduler constructions pass `finance=None`)
- Related: existing `docs/runbooks/` incident runbooks; core service health /
  outage runbooks (worker lives in the `services/core` process)