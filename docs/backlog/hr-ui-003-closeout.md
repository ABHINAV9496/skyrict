# HR-UI-003 — Close-out

HR/Payroll workspace UI: §7.1/§7.2 sidebar scrollbar + chevron-pill styling, §7.3
HR/Payroll home overviews with click-through summaries, §7.4 dark-mode portal
containment, §7.5 module-home setup checklists, §8.1 employment-status transitions
and compensation current-rate/history, and §8.2 per-entry payroll adjustments. This
document records the deliverables, the locked design decisions, the verification
evidence, and the PR notes/caveats reviewers should know.

Verification status: **all §7/§8 items delivered — rendered-UI gates 36/36 green**
(`gates.js`), plus per-phase checkpoints `checkpoint-75.js` 16/16, `checkpoint-6.js`
27/27 (read-only gating), `checkpoint-81.js` 12/12 (status transitions),
`checkpoint-82.js` 12/12 (adjustments). Static gates (`tsc --noEmit`, `eslint .`,
`next build`) green at HEAD; no new repository dependencies. Live stack: identity +
core in Docker, Next dev server on `:3000`. Commit range `44963eb..HEAD` = 10
commits.

---

## Deliverables vs. ticket items

| § | Item | Status | Evidence |
|---|------|--------|----------|
| 7.1 | Sidebar nav uses the themed scrollbar | Done | `.themed-scrollbar` on `<nav aria-label="Dashboard">` (`app-sidebar.tsx:305`), verified in Gate 5 |
| 7.2 | Chevron sits inside the active rounded row pill, no background of its own | Done | chevron button (`app-sidebar.tsx:184-196`) inside the `rounded-lg` pill (`:158-165`), `d334104`; Gate 5 asserts pill `rounded-lg` + `bg-sidebar-accent` + chevron has no `bg-` |
| 7.3 | HR home overview + Payroll home overview with click-through summaries | Done | `hr-overview.tsx`, `payroll-overview.tsx`, shared `stat-card`/`status-breakdown`/`recent-activity-list` (`aa7bfce`); Gates 1/2/3/6 |
| 7.4 | Radix Dialog/Select portals render inside the module theme world (dark mode) | Done | portal container resolution in `theme-world.ts` (`getThemeContainer`, `data-theme-world="erp"`), `0dbd14f`; Gate 4 asserts dialog + listbox inside the ERP theme world in dark and light |
| 7.5 | Module-home setup checklists (HR + Payroll) | Done | shared `setup-checklist.tsx` + extracted `department-dialog`/`compensation-dialog`/`run-dialog` (`7f75197`); Gates 8 + `checkpoint-75.js` |
| 7.6 | Parent sidebar row stays a navigable Link with a chevron toggle | Done (no change) | user directive confirmed against the existing implementation — parent row is a Link, chevron toggles the group; re-verified 18/18, no code change |
| 8.1 | Employment-status transitions (place on leave / reactivate) + compensation current rate & history | Done | employee-detail lifecycle actions (`c1b3f62`); current-rate line + history on the compensation page; Gate 9 + `checkpoint-81.js` |
| 8.2 | Per-entry adjustments on draft/computed runs, sign convention, read-only after approval | Done | run-detail Adjust affordance + dialog (`4048bb3`), sign fix (`c6f6ba4`); Gate 10 + `checkpoint-82.js` |

## §7.3 locked design decisions (as shipped)

- Overview sits on top of the module home; the existing list entry points remain
  below as "Explore" cards.
- HR KPIs — **Active employees / Open leave requests / On leave now /
  Departments**; Payroll KPIs — **Payroll runs / Draft runs / Paid runs /
  Latest run**.
- Status breakdown cards ("Leave requests by status", "Runs by status") and the
  recent-activity list render above their plain list pages, click-through via the
  breakdown row links to the corresponding filtered list view
  (`/erp/hr/leave?status=pending`, `/erp/payroll/runs?status=draft`).
- Counts are honest: `apiList` probes with `limit + 1` and `formatListCount`
  appends `+` whenever a following page exists (`lib/format.ts:81-86`) — a total
  is never guessed.
- Zero-data states render gracefully ("No records yet.", "No leave activity yet —
  hire a team member or create a leave request.").

## §7.5 / §8 locked design decisions (as shipped)

- **Setup checklists (§7.5).** The module home shows a checklist while the
  tenant is not "done": HR = 3 steps (hire / department / leave request), Payroll
  = 2 steps (compensation record / run), each with a "Done" badge or a primary
  action (which the shared dialog triggers). A fully-done tenant renders no
  checklist at all (`hr-setup.tsx`/`payroll-setup.tsx` return `null` while
  loading, so the checklist mounts after the data fetch — the gate script waits
  for the panel rather than the KPI grid).
- **Compensation page (§8.1).** Shows the current rate line
  (`currently US$5,000.00/month`) and a History table; the current rate comes
  from `activeCompensation` on the employee list (backend enrichment, `6080d98`),
  not a separate fetch.
- **Adjustments (§8.2).** Every draft/computed run entry renders an **Adjust**
  button; the dialog amount is a **deduction** (net = gross − PF − tax − adj), a
  positive amount lowers net; entry rows are read-only once the run is approved
  (no Adjust affordance), with a "Read-only after approval" hint on computed runs.
  Computed runs remain adjustable (matching the backend, which blocks
  APPROVED/PAID only).

## Verification gate

Live stack: `skyrict-identity` (:8000) + `skyrict-core` (:8001) in Docker,
Postgres on host `:5433`, Next dev server `:3000`, Playwright 1.62.1.
Gate script: `pwshot/gates.js` (login with known MFA TOTP secrets, tour suppressed
via `localStorage["skyrict:product-tour-seen"]`).

| Gate | Check | Result |
|------|-------|--------|
| 1 | bridgeon HR home — KPI row renders; empty-state breakdown + activity | PASS (`Active employees=1, Open leave requests=0, On leave now=0, Departments=1`) |
| 6 | olympus HR home — populated KPIs (`4 / 1 / 1 / 2`); breakdown counts Pending/Approved/Rejected/Cancelled = 1 each; recent activity non-empty | PASS |
| 2 | Breakdown "Pending" click-through → `/erp/hr/leave?status=pending`; Leave status Select shows Pending | PASS |
| 3 | olympus payroll KPIs (`Payroll runs=5, Draft=1, Paid=1, Latest run=US$23,000.00`); runs breakdown Draft/Computed/Approved/Paid/Void = 1 each; recent runs show PR-5; "Draft" click-through → `/erp/payroll/runs?status=draft`; bridgeon payroll empty states | PASS |
| 4 | §7.4 — Dialog (dark), Select listbox (dark), Dialog (light) all render inside `[data-theme-world="erp"]` | PASS (`erp`) |
| 5 | §7.1/§7.2 — nav has `themed-scrollbar`; chevron inside active `rounded-lg` pill with no own `bg-` | PASS |
| 7 | §7.3 tenant isolation — bridgeon/olympus employee + department lists each contain only their own rows | PASS |
| 8 | §7.5 — bridgeon HR checklist present with `2 of 3 done` + two Done badges; bridgeon payroll checklist `1 of 2 done`; olympus HR/payroll checklists hidden | PASS |
| 9 | §8.1 — compensation current-rate line `currently US$5,000.00/month`; history rows render | PASS |
| 10 | §8.2 — computed run: one Adjust per entry (4/4) + "Read-only after approval" hint; paid run: no Adjust buttons | PASS |
| — | No error banners on olympus pages (excluding Next.js route announcer) | PASS (`0 alerts`) |

**36/36 checks passed.** Screenshots (all captured): `gate6-hr-home-bridgeon.png`,
`gate6-hr-home-olympus.png`, `gate2-leave-filtered.png`, `gate3-payroll-home-olympus.png`,
`gate4-dialog-dark.png`, `gate4-select-dark.png`, `gate4-dialog-light.png`,
`gate5-sidebar-hover.png`, `gate8-bridgeon-payroll-checklist.png`,
`gate9-compensation-current-rate.png`, plus the phase checkpoints below.

### Per-phase checkpoints (Playwright, same stack)

| Script | Coverage | Result |
|--------|----------|--------|
| `checkpoint-75.js` | §7.5 — checklists on both homes, progress/done badges, panels hidden when done, shared dialogs open from checklist + list pages | 16/16 |
| `checkpoint-6.js` | Read-only gating — auditor user (`ui.readonly@olympus.dev`) sees HR/Payroll but zero write actions anywhere; API GET 200 / POST 403; org-admin sees all write actions | 27/27 |
| `checkpoint-81.js` | §8.1 — place-on-leave/reactivate buttons by status, no buttons for a terminated fixture, status restored | 12/12 |
| `checkpoint-82.js` | §8.2 — Adjust per computed entry, sign convention, read-only approved/paid runs | 12/12 |

Static gates at HEAD: `tsc --noEmit`, `eslint .`, and `next build` all green; no
new repository dependencies.

---

## PR notes / caveats

1. **Scope drift.** The ticket's §7.3 "home overview" expanded into a §7
   addendum covering §7.4 (portal containment in the module theme world,
   `0dbd14f`) and §7.1/§7.2 (sidebar scrollbar + chevron pill, `d334104`),
   plus a pre-§7 checkpoint commit (`44963eb`: BFF proxy routing, HR/Payroll
   API clients, sidebar permission gating, ERP page shells). Each boundary was
   kept in its own commit.

2. **Mock deletion divergence.** The ERP mock (`lib/mock/erp.ts`) was removed
   and the UI now talks to the live backend (`d364d83` = HR-BE-002 backend
   merge). Any behavior previously asserted against the mock will diverge from
   production responses (e.g. bare-array lists with no `meta`, snake_case
   payloads mapped to camelCase in `hr-api.ts`/`payroll-api.ts`).

3. **Synthesized totals.** The backend list endpoints return bare arrays, so
   `apiList` (`lib/api/http.ts:211-244`) synthesizes `PaginationMeta` from a
   `limit + 1` probe. `total`/`total_pages` are therefore "at least" values and
   `formatListCount` renders a trailing `+` when a following page exists. No
   invented exact counts anywhere.

4. **Core-RBAC provisioning gap (pre-existing, infra only).** The UI-check
   users were created with core role grants (`core_user_roles`) but **no
   identity role grants** (`user_roles`), which is what identity's
   `GET /roles/me` reads — so every ERP page rendered "No access to Business
   Operations". Additionally the olympus tenant had **no identity system roles
   at all**. Both were fixed at the data layer via `fix_rbac.py`
   (identity `user_roles` grants: `tenant_owner` → bridgeon check user,
   `organization_admin` → olympus check user, plus olympus system roles). This
   is environment/seed work, **not** part of the §7 commit range.

5. **§7.4 classification.** The portal-containment defect (Radix portals
   escaping the module theme-world wrapper and rendering against the global
   theme) was **pre-existing**, not introduced by §7.3 — the ERP page shells
   were the first Radix-in-theme-world surfaces. Fixed in `0dbd14f` within §7
   scope.

6. **Shared-primitive extraction.** `stat-card.tsx`, `status-breakdown.tsx`,
   and `recent-activity-list.tsx` were extracted under
   `components/dashboard/shared/` for the overviews. The Reports KPI cards and
   Finance modules reuse the same visual language and are flagged as adoption
   candidates (out of HR-UI-003 scope).

7. **Dev-server restart required.** RSC/layout changes require a clean Next dev
   server restart before verification; stale module state produced
   Client/Server-mismatch style failures during the gate runs.

8. **`next build` must not run while `next dev` is up.** Build and dev share
   `apps/web/.next`; a production build run against a live dev server corrupted
   the dev server's compile state and the signin surface began returning 500.
   Recovery = restart the dev server. Verification order for future phases: run
   static gates first, then restart dev, then run Playwright.

9. **`active_compensation` list enrichment (backend fix, `6080d98`).** The
   employee list previously returned a null compensation payload, so the §8.1
   compensation page had nothing to render a "current rate" from. Fixed in the
   core router (`services/core/.../routers/hr.py`) by populating
   `active_compensation` in the list serializer — the one code change outside
   `apps/web` in this range.

10. **Adjustment sign convention (§8.2).** Matches the backend: a stored
    adjustment `amount` is a **deduction** (`net = gross − pf − tax − adj`); the
    UI dialog labels it "Adjustment (deduction)" and `c6f6ba4` fixed the
    form-to-payload sign so a positive input lowers net. Do not "fix" the sign
    without re-reading HR-BE-002 semantics.

11. **VOID runs stay adjustable (backend gap, logged only).** The backend
    adjustment guard blocks APPROVED and PAID runs but **not VOID** — so a VOID
    run's entries are technically still mutable at the API level. The UI shows no
    Adjust affordance on void runs (treats void like approved/paid), so this is
    not user-visible; flagging for a future backend guard if voided runs must be
    immutable.

12. **Read-only verification user (data-layer only, not in source).**
    `ui.readonly@olympus.dev` (auditor) was provisioned directly in the identity
    and core databases (users row + `user_roles` identity grant + `core_user_roles`
    core grant) for `checkpoint-6.js`. Like the other UI-check users, it lives in
    the environment, **not** in repo seed data. Identity role → permissions
    mapping: `GET /roles/me` returns `erp.hr.read`/`erp.payroll.read` only; the
    UI hides every write affordance and the BFF returns 403 for POSTs.

13. **Checklist mount timing.** `hr-setup.tsx`/`payroll-setup.tsx` return `null`
    while their data loads, so the checklist mounts well after the KPI grid —
    gate assertions must wait for the panel itself (a cold dev-server restart
    makes the first data fetch slow enough to fail immediate checks).

---

## Findings beyond scope (logged, not fixed here)

- **Browser-only session-loss race (dev/automation).** On the dev server, a
  full-page navigation started immediately after login can abort the previous
  page's in-flight `/api/auth/session` refresh: identity rotates the refresh
  token, but the browser never commits the `Set-Cookie`, so the next page
  presents the stale token and the identity **reuse detector revokes the whole
  token family** (`auth.refresh.reuse_detected`), landing the user back on
  signin with a cleared cookie. Real users click after the page settles, so this
  does not reproduce in manual use. The gate script mitigates it by waiting for
  the sidebar to render plus a 1.5s settle before any cross-page navigation.
  Worth a follow-up: a request-level single-flight that also covers aborted
  rotations.
- **`[role="alert"]` noise.** Next.js injects `#__next-route-announcer__`
  (an always-present live region) on every page; error-banner assertions must
  exclude it.

---

## Commit range

`git log --oneline 44963eb..HEAD` = **10 commits**:

```
6080d98 fix(core): [HR-UI-003 §7.5] populate active_compensation in employee list
7f75197 feat(web): [HR-UI-003 §7.5] setup checklists on HR and payroll homes
c1b3f62 feat(web): [HR-UI-003 §8.1] employment status transitions (place on leave / reactivate) on employee detail
c6f6ba4 fix(web): [HR-UI-003 §8.2] match backend adjustment sign (positive amount = deduction)
4048bb3 feat(web): [HR-UI-003 §8.2] per-entry adjustments on draft/computed payroll runs
fd9f250 docs: [HR-UI-003] close-out notes for HR/Payroll workspace UI
aa7bfce feat(web): [HR-UI-003 §7.3] HR and Payroll home overviews with click-through summaries
d334104 fix(web): [HR-UI-003 §7.1/§7.2] themed sidebar scrollbar + chevron inside row pill
0dbd14f fix(web): [HR-UI-003 §7.4] mount Radix portals inside the module-world wrapper
44963eb checkpoint: HR-UI-003 pre-§7 fixes (BFF, clients, sidebar, pages)
```
