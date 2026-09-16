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
