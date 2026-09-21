# Dev Environment Known Issues & Loose Ends

Tracking home for non-incident dev-environment state that could surprise
someone later. This is **not** incident response — see
[`docs/runbooks/README.md`](./README.md) for operational incident runbooks.
Add one short entry here for any deliberate-but-undeclared dev-env state
change instead of letting it fade into a chat log.

---

## Entry A — bridgeon-solutions auth weakening (dev tenant)

**Status: known, restore deliberately deferred.**

While running the HR-AI-001 close-out live gates (compliance, then the
combined attrition + payroll-anomalies + compliance walkthrough), MFA was
disabled on **`abhikrishna616@gmail.com`** (the `bridgeon-solutions`
tenant_owner) to allow headless credential login. Same was done earlier for
`admin@bridgeon.io` (org_admin).

Current DB state (`users` table in `skyrict_identity`):

| account                    | mfa_enabled | mfa_secret |
| -------------------------- | ----------- | ---------- |
| `abhikrishna616@gmail.com` | **false**   | set        |
| `admin@bridgeon.io`        | true        | set        |

Notes:

- `abhikrishna616`'s password is a known plaintext used by the gate scripts
  (`abhikrishna 61@`). Treat it as a shared/dev secret.
- The dev database has been re-seeded more than once this session; any
  re-seed resets MFA/password state, so verify before assuming.
- **Before using `bridgeon-solutions` for anything real**, re-enable MFA and
  rotate to a non-shared password on the accounts above.

### Update (2026-09-07)

MFA is now **enrolled** on `abhikrishna616@gmail.com` (`mfa_enabled=true`)
with a known dev TOTP secret, and the password was rotated to
`Abhikrishna61@` during the HR-UI-003 gate run (screenshot pass). Prior
state above is stale on the password. Verify via the DB before assuming;
rotate both again before any real use of the tenant. The dev TOTP secret is
recorded in the gate tooling (temp scripts), not in the repo.

---

## Entry B — identity migration stamp conflict (teammate's unpushed branch)

**Status: known, reconcile when the branch merges.**

The dev `skyrict_identity` database was stamped ahead at migration `0020`
from a teammate's unpushed branch, which implemented its own conflicting
self-service naming variant:

- teammate: permission `hr.leave.self` + role `employee`
- this work: permission `erp.leave.self` + role `employee_self_service`

At the time, the `0018_employee_self_service` migration payload was applied
manually via `psql` rather than running `alembic upgrade head`, specifically
to avoid fighting that stamp.

**Do NOT blindly run `alembic upgrade head` on identity in this dev
environment — check the current stamp first.** The naming collision must be
reconciled (one naming choice wins, migrations properly chained) whenever
that teammate's branch actually merges.

---

## Entry C — bridgeon-solutions RBAC dropped by re-seed (restored)

**Status: fixed, worth knowing if you hit "No spaces available".**

A re-seed of `skyrict_identity` left the `bridgeon-solutions` tenant with its
users but **no RBAC rows** (zero `roles`, `memberships`, and `user_roles` for
that tenant). Symptom: `abhikrishna616@gmail.com` logs in fine but the
frontend shows _"No spaces available yet. Contact a workspace owner to grant
you access."_ — there is no active membership/role scope behind the user.

Restored on `2026-09-03` by running an idempotent script through the app's own
repositories (`RoleRepository` + `MembershipRepository`), mirroring
`identity/seed.py`:

- created the 6 `SYSTEM_ROLE_DEFINITIONS` roles scoped to `bridgeon-solutions`
- created the active `tenant_owner` membership for `abhikrishna616@gmail.com`
- created the tenant-scoped `user_roles` grant

Verified `roles_for_user = ['tenant_owner']` (full `*` → HR + payroll). A user
must **log out/in** to pick up the restored membership.

If a future re-seed drops RBAC again, re-run the equivalent restore (roles +
membership + grant) rather than assuming the account is broken.

---

## Entry D — bridgeon-solutions demo data is now Indian-realistic (INR)

**Status: fixed in seed source + live DB.**

`seed_demo.py` now seeds the `bridgeon-solutions` demo roster as an Indian
IT-services company instead of generic US names. When re-seeded with
`--force --employees 30` this produces:

- 30 employees (Indian names, `@bridgeonsolutions.com` emails, `+91` phones,
  SBI bank accounts), 1 terminated; index 13 is the terminated +
  uncompensated HR-AI ghost fixature target.
- Compensation in **INR** ₹55K–₹195K monthly (29 active rows; index 13
  intentionally uncompensated to exercise the seed's skip path).
- Payroll runs through PR-2026-09 (paid/approved/computed).
- Indian statutory benefits (EPF, ESI, GTL) and Indian public holidays.

The per-tenant `erp_payroll_settings.default_currency` for this tenant was
flipped **USD → INR** via manual DB update. It is **not** encoded in the seed —
any full re-seed that recreates that row (e.g. a wiped `skyrict_identity`) will
default it back to `settings.DEFAULT_CURRENCY` (USD). Re-flip after reseeding.
Note the finance/CIM seeders (`seed_crm`, `seed_revenue_history`,
`seed_overdue_invoices`, sales orders) still use USD — that is a deliberate,
detached seam: only HR/payroll is INR.

---

## Entry E — 3 pre-existing core migration-downgrade test failures (not this branch)

**Status: open upstream issue, not introduced by fix/BUG-WEB-001.**

Three `services/core/tests/integration/database` alembic downgrade round-trip
tests fail on the live dev DB:

- `test_crm_sales.py::TestDowngradeRoundTrip::test_downgrade_then_upgrade_restores_head`
- `test_crm_workspace.py::TestDowngradeRoundTrip0016::test_downgrade_to_0015_then_upgrade_restores_head`
- `test_report_cache_repository.py::TestCacheRoundTrip::test_delete_expired_purges_only_expired`

Failure signature (all three): `asyncpg.exceptions.DependentObjectsStillExistError:
cannot drop table erp_documents because other objects depend on it` — the
downgrade from revision 0049 → 0048 (SKY-87 document management spine) tries to
drop `erp_documents`, but later revisions (or objects created by them) still
reference it, so the migration cannot unwind below 0048.

Verified **pre-existing**: `git diff origin/dev...HEAD` on the failing test
files and `services/core/alembic/` is **empty** — the branch under test
(introduced no migration changes) neither introduced nor worsened these. They
also reproduce on the parent of the branch tip.

**Repro:** with a DB migrated to core head, run:

```
pytest services/core/tests/integration/database/test_crm_sales.py::TestDowngradeRoundTrip
```

**Likely fix (not done here):** the 0048 downgrade must drop (or the later
revisions must drop) the dependent objects first — e.g. `erp_document_chunks` /
FK back-edges created post-0048 — before `erp_documents`. Needs an upstream
migration fix authored against origin/dev, out of scope for this branch.

---

## Entry F — sentry-sdk missing from the local venv (stale, not lockfile drift)

**Status: resolved, local-only.**

`mypy services/ libs/` failed with `Cannot find implementation or library stub
for module named "sentry_sdk"` even though `sentry-sdk[fastapi]>=2.14,<3` is a
declared dependency of identity/core/ai-agent. Root cause: the local `.venv`
was bootstrapped (with bare `pip`, after `ensurepip`) before uv's lockfile
pinned sentry-sdk at `2.69.2` (commit `22fa93fb`, "add sentry-sdk fastapi extra
to uv.lock", 2026-09-15) — so the package was never installed locally.

Not a lockfile/dependency-drift issue: `uv.lock` resolves
`sentry-sdk==2.69.2` for all three services, and CI installs via
`uv sync --all-packages`, so a fresh clone gets it. Fix applied locally:
`python -m pip install "sentry-sdk[fastapi]>=2.14,<3"` → mypy now green
(921 files, no issues). If mypy complains about `sentry_sdk` again, run
`uv sync --all-packages` (or the equivalent pip install) first.

---

## Entry G — duplicated date/money formatters across web modules

**Status: open, consolidation deferred (semantics differ per module).**

`formatDate` is declared in **5** modules with **3** distinct behaviors:

| location                       | UTC-anchors date-only | invalid input | locale      |
| ------------------------------ | --------------------- | ------------- | ----------- |
| `lib/format.ts:39`             | **yes** (`timeZone: "UTC"`) | `"-"`   | viewer      |
| `lib/finance/format.ts:66`     | no                    | raw string    | viewer      |
| `lib/erp/money.ts:37`          | no                    | raw string    | hardcoded `en-US` |
| `lib/api/inventory-api.ts:1046`| no                    | `"-"`         | viewer      |
| `lib/api/documents-api.ts:441` | no (identical to inventory) | `"-"`  | viewer      |

`formatMoney` is declared in **4** modules, no two alike:

- `lib/format.ts:22` — `(amount, currency = "USD")`, passes the decimal
  **string straight to `Intl`** (never `Number()`), viewer locale.
- `lib/finance/format.ts:16` — single arg, `Number()` coercion, NaN → returns
  the **raw string**, `en-US`, min 2 fraction digits.
- `lib/erp/money.ts:9` — `(amount, currency?)`, `Number()` coercion, `en-US`,
  max 2 fraction digits, try/catch fallback for an invalid currency code.
- `lib/api/inventory-api.ts:1038` — takes a `[amount, currency]` `Money` tuple
  and does **no `Intl` at all** (`${amount} ${currency}`).

**Do not blind-merge these.** The UTC-anchor difference is load-bearing:
date-only strings (payroll periods, leave/holiday dates) rendered with the
non-anchored copies shift by a day for viewers west of UTC. The NaN→raw-string
vs NaN→`"-"` split also changes visible output on malformed rows. Any
consolidation must trace each call site and pick the intended behavior per
module before collapsing.

---

## Entry H — four table components, two incompatible pagination shapes

**Status: open, unification deferred (blocked on a consumer audit).**

Two shared table implementations coexist:

- `components/dashboard/erp/erp-table.tsx` — static, no pagination.
- `components/dashboard/shared/erp-data-table.tsx` — paginated,
  `T extends { id: string }`.

`ErpColumn<T>` is defined twice with **different `key` types**:
`key: string` (`erp-table.tsx:8`) vs `key: keyof T & string`
(`shared/erp-data-table.tsx:11`). The stricter form catches typos but the
looser form has **7** consumers importing from `erp-table.tsx` (crm
activities/contacts/customers/leads tables, crm customer-detail, sales
orders-table, sales order-detail) — merging requires auditing all of them.

`PaginationMeta` is defined **4** times in **two incompatible shapes**:

- snake_case `total_pages` — `lib/api/http.ts:21`, `lib/api/crm-api.ts:53`.
- camelCase `totalPages` — `lib/api/documents-api.ts:27`,
  `lib/api/inventory-api.ts:19`. These two APIs each run a local `mapMeta()`
  converting the wire `total_pages` → `totalPages`; the snake-case APIs carry
  the wire shape straight through.

A blind merge would break pagination on the documents/inventory pages, since
their components read `meta.totalPages`, not `meta.total_pages`.

---

## Entry I — per-page `PageStatus` unions (no shared list-state hook)

**Status: open, refactor deferred (mechanical diff across ~29 files).**

`type PageStatus` is declared locally in **29** files — e.g.
`app/dashboard/roles/roles.tsx`, `features/finance/settings.tsx`, the payroll
pages, every CRM table/detail, sales, and the HR pages — each a near-identical
`loading | ready | error | empty` union parameterized by that page's payload.

A shared `PageStatus<T>` plus a `useApiList()` hook would remove the repeated
load/guard/`useLatestRequest` boilerplate, but every variant differs slightly
in its extra states, so it lands as a large mechanical diff. Deferred off
`fix/BUG-WEB-001` to keep that branch reviewable; do it as its own change with
the page-by-page behavior diff checked.

---

## Entry J — bridgeon-solutions demo tenant provisioned by a local-only script

**Status: fixed, repeatable — on machines that carry the maintenance script.**

The `bridgeon-solutions` demo tenant was previously created ad hoc in the dev
DB (Entries A/C/D) — nothing in the repo or the E2E compose stack reproduced
it, so a fresh stack came up with only the `default` tenant. Provisioning now
lives in `services/identity/src/identity/seed_bridgeon.py` — an idempotent
script that is **untracked and gitignored** on purpose. It runs from the
bind-mounted host source of the running compose stack, so it works locally but
is NOT part of the repo tree, is not shipped by CI, and is missing from fresh
clones. The identity container sees it because compose mounts
`../../services/identity/src` into `/app/services/identity/src`.

```
docker exec skyrict-e2e-identity \
  uv run --directory services/identity python -m identity.seed_bridgeon
```

It creates the tenant (fixed UUID `00000000-0000-0000-0000-000000000002`,
slug `bridgeon-solutions`), the six `SYSTEM_ROLE_DEFINITIONS` roles, the
`abhikrishna616@gmail.com` (`tenant_owner`) and `admin@bridgeon.io`
(`organization_admin`) users, and their active membership + tenant-scoped
grants. MFA is seeded **enrolled** on both with the fixed dev TOTP secret
`JBSWY3DPEHPK3PXP` (same posture as Entry A, so headless gate logins can pass
the mandatory `mfa.verify` challenge). Rotate the secret and passwords before
real use.

Then seed core data for that tenant (dashes, not underscores):

```
docker exec skyrict-e2e-core uv run --directory services/core \
  python -m core.cli seed --tenant-id 00000000-0000-0000-0000-000000000002
docker exec skyrict-e2e-core uv run --directory services/core \
  python -m core.cli seed-demo --tenant-id 00000000-0000-0000-0000-000000000002 --force --employees 30
docker exec skyrict-e2e-core uv run --directory services/core \
  python -m core.cli seed-crm --tenant-id 00000000-0000-0000-0000-000000000002 --force
docker exec skyrict-e2e-core uv run --directory services/core \
  python -m core.cli seed-revenue-history --tenant-id 00000000-0000-0000-0000-000000000002
docker exec skyrict-e2e-core uv run --directory services/core \
  python -m core.cli seed-overdue-invoices --tenant-id 00000000-0000-0000-0000-000000000002
```

Two post-seed steps the seeders do **not** encode (same caveats as Entry D):

1. Flip payroll currency to INR:
   `UPDATE erp_payroll_settings SET default_currency = 'INR' WHERE tenant_id = '00000000-0000-0000-0000-000000000002';`
2. Restart core (`docker restart skyrict-e2e-core`) so the boot-time
   `sync_rbac_from_identity` copies the new identity grants into
   `core_user_roles` — without it the tenant owner authenticates but
   `require_permission` denies in core.

Verified live: login as `abhikrishna616@gmail.com` / `Abhikrishna61@`
(`X-Tenant-Slug: bridgeon-solutions`) → `mfa.verify` challenge → TOTP from
`JBSWY3DPEHPK3PXP` → 200 with a tenant-scoped token;
`GET /api/v1/hr/employees` → 200 with the 30-employee Indian roster; 18
payroll runs, 85 journal entries, INR payroll settings.
