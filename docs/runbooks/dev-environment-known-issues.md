# Dev Environment Known Issues & Loose Ends

Tracking home for non-incident dev-environment state that could surprise
someone later. This is **not** incident response — see
[`docs/runbooks/README.md`](./README.md) for operational incident runbooks.
Add one short entry here for any deliberate-but-undeclared dev-env state
change instead of letting it fade into a chat log.

---

## Entry A — bridgeon-solutions auth hardening (dev tenant)

**Status: fixed (SEC-CLEAN-001) — rotated, MFA enforced, no plaintext in repo.**

The `bridgeon-solutions` demo accounts previously carried known plaintext
passwords and a recorded dev TOTP secret in this runbook and in the seed
script, and the seed held a real personal email address (a team member's).
As of SEC-CLEAN-001 the demo identities are a
**synthetic roster** — realistic but entirely fake people on the reserved
`bridgeon.example` domain, no real personal data — the credentials have been
**rotated**, and the plaintext scrubbed from the repo, runbook, and scripts.
The old values (also present in pre-rotation git history) are dead and must
never be reused.

Where credentials live now:

- The seeder reads passwords + TOTP secret from `settings.SEED_BRIDGEON_*`
  (env vars). Values exist **only** in the gitignored
  `services/identity/.env` — never in the repo, this runbook, or any script.
  The seeder fails fast when they are missing; there is deliberately no
  hardcoded fallback.
- MFA is **enrolled** on every seeded account (`users.mfa_enabled=true`,
  TOTP secret encrypted at rest with `MFA_ENCRYPTION_KEY`). MFA is mandatory
  in-app, so login always requires the TOTP challenge.

### Rotation policy (SEC-CLEAN-001)

The seeder *is* the rotation mechanism — rotating credentials is:

1. Edit the gitignored `services/identity/.env`:
   `IDENTITY_SEED_BRIDGEON_OWNER_PASSWORD`,
   `IDENTITY_SEED_BRIDGEON_ORG_ADMIN_PASSWORD`,
   `IDENTITY_SEED_BRIDGEON_TEAM_PASSWORD`,
   `IDENTITY_SEED_BRIDGEON_MFA_SECRET` (must satisfy the configured password
   policy; generate the TOTP secret with
   `python -c "import pyotp; print(pyotp.random_base32())"` or equivalent).
2. Re-run `python -m identity.seed_bridgeon` — the seeder re-applies the
   password hashes and MFA secret to the existing accounts (see Entry J for
   the container invocation, which must pass the vars via `docker exec -e`).
3. Verify: psql-check `users.mfa_enabled`, then a real login through the
   full MFA challenge with the new TOTP secret.

Never write a credential value into this file, any script, or any commit;
if one is ever needed in a shared doc, reference the env var name instead.

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

## Entry C — bridgeon-solutions RBAC dropped by re-seed (root-caused & eliminated)

**Status: fixed (SEC-CLEAN-001) — root cause eliminated, regression-tested.**

Historical incident: a re-seed of `skyrict_identity` left the
`bridgeon-solutions` tenant with its users but **no RBAC rows** (zero
`roles`, `memberships`, and `user_roles` for that tenant). Symptom:
`aarav.deshmukh@bridgeon.example` (tenant_owner) logs in fine but the
frontend shows _"No spaces
available yet. Contact a workspace owner to grant you access."_ — no active
membership/role scope behind the user. Restored on `2026-09-03` by an
idempotent script through `RoleRepository` + `MembershipRepository`.

**Root cause** (why it happened, not just what happened): the provisioning
that created the tenant + users did not create the RBAC trio, and the
restore path lived in a gitignored, untracked script with no CI coverage —
so nothing enforced completeness and nothing prevented (or detected) the
partial state. That untracked script was itself a symptom of the same
failure mode SEC-CLEAN-001 fixes: a fix with no CI gate can silently degrade
until it breaks live.

**Fix**: `services/identity/src/identity/seed.py` and
`seed_bridgeon.py` now create users, roles, memberships, and grants in ONE
transaction (single commit; completeness check before commit). A failure
mid-seed rolls back everything, so the "users but no RBAC rows" shape can
never be committed — the tenant either exists complete or not at all. The
bridgeon seeder is tracked in the repo and covered by
`services/identity/tests/integration/api/test_seed_bridgeon_rbac.py`
(re-seed preserves the RBAC row set; credential rotation preserves it; a
tenant degraded to the Entry C shape is repaired by a single re-run), which
runs in CI. A user recovering from a degraded state must **log out/in** to
pick up a restored membership.

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

## Entry J — bridgeon-solutions demo tenant seeded from the repo (SEC-CLEAN-001)

**Status: fixed, repeatable, CI-covered.**

The `bridgeon-solutions` demo tenant was previously created ad hoc in the dev
DB (Entries A/C/D) — nothing in the repo or the E2E compose stack reproduced
it, so a fresh stack came up with only the `default` tenant. Provisioning now
lives in `services/identity/src/identity/seed_bridgeon.py` — tracked in the
repo, idempotent, single-transaction (Entry C), and covered by the
integration regression test
`services/identity/tests/integration/api/test_seed_bridgeon_rbac.py` which
runs in CI. Credentials are read from `settings.SEED_BRIDGEON_*` (gitignored
`services/identity/.env` — no plaintext in the repo; see Entry A for the
rotation policy); the seeder fails fast when they are missing.

Invocation — when running inside a container, pass the three
`IDENTITY_SEED_BRIDGEON_*` vars explicitly (the compose identity service gets
its env inline, not from the host `.env`):

```
docker exec skyrict-e2e-identity \
  env IDENTITY_SEED_BRIDGEON_OWNER_PASSWORD='<owner password from .env>' \
      IDENTITY_SEED_BRIDGEON_ORG_ADMIN_PASSWORD='<org admin password from .env>' \
      IDENTITY_SEED_BRIDGEON_TEAM_PASSWORD='<team password from .env>' \
      IDENTITY_SEED_BRIDGEON_MFA_SECRET='<totp secret from .env>' \
  uv run --directory services/identity python -m identity.seed_bridgeon
```

On the host, running `uv run --directory services/identity python -m
identity.seed_bridgeon` from the repo root picks the values up from
`services/identity/.env` automatically. Never print or commit the values.

It creates the tenant (fixed UUID `00000000-0000-0000-0000-000000000002`,
slug `bridgeon-solutions`), the six `SYSTEM_ROLE_DEFINITIONS` roles, and a
realistic but entirely fake demo roster — eight `bridgeon.example`-domain
identities spanning all six roles (tenant owner, org admin, managers,
standard users, auditor, self-service) — each with an active membership +
tenant-scoped grant, all in **one transaction**. MFA is seeded **enrolled**
on every seed account with the configured TOTP secret (Entry A posture), so
headless gate logins pass the mandatory `mfa.verify` challenge. Rotating
credentials = edit `.env` + re-run (Entry A).

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

Verified live: login as `aarav.deshmukh@bridgeon.example` (tenant_owner)
with the credentials in
`services/identity/.env` (`X-Tenant-Slug: bridgeon-solutions`) → `mfa.verify`
challenge against the configured TOTP secret → 200 with a tenant-scoped
token; `GET /api/v1/hr/employees` → 200 with the 30-employee Indian roster;
18 payroll runs, 85 journal entries, INR payroll settings.
