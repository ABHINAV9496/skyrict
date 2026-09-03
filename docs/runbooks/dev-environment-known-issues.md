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

| account | mfa_enabled | mfa_secret |
|---------|-------------|------------|
| `abhikrishna616@gmail.com` | **false** | set |
| `admin@bridgeon.io` | true | set |

Notes:

- `abhikrishna616`'s password is a known plaintext used by the gate scripts
  (`abhikrishna 61@`). Treat it as a shared/dev secret.
- The dev database has been re-seeded more than once this session; any
  re-seed resets MFA/password state, so verify before assuming.
- **Before using `bridgeon-solutions` for anything real**, re-enable MFA and
  rotate to a non-shared password on the accounts above.

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
frontend shows *"No spaces available yet. Contact a workspace owner to grant
you access."* — there is no active membership/role scope behind the user.

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
