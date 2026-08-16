# HR-UI-003 — Close-out (§7 addendum)

HR/Payroll workspace UI: §7.1/§7.2 sidebar scrollbar + chevron-pill styling, §7.3
HR/Payroll home overviews with click-through summaries, and §7.4 dark-mode portal
containment. This document records the deliverable, the locked design decisions,
the verification evidence, and the PR notes/caveats reviewers should know.

Verification status: **all §7 items delivered, rendered-UI gates 20/20 green**
via Playwright against the live stack (identity + core in Docker, Next dev server
on `:3000`). Commit range `44963eb..HEAD` = 4 commits.

---

## Deliverables vs. §7 items

| §7 | Item | Status | Evidence |
|----|------|--------|----------|
| 7.1 | Sidebar nav uses the themed scrollbar | Done | `.themed-scrollbar` on `<nav aria-label="Dashboard">` (`app-sidebar.tsx:305`), verified in Gate 5 |
| 7.2 | Chevron sits inside the active rounded row pill, no background of its own | Done | chevron button (`app-sidebar.tsx:184-196`) inside the `rounded-lg` pill (`:158-165`), `d334104`; Gate 5 asserts pill `rounded-lg` + `bg-sidebar-accent` + chevron has no `bg-` |
| 7.3 | HR home overview + Payroll home overview with click-through summaries | Done | `hr-overview.tsx`, `payroll-overview.tsx`, shared `stat-card`/`status-breakdown`/`recent-activity-list` (`aa7bfce`); Gates 1/2/3/6 |
| 7.4 | Radix Dialog/Select portals render inside the module theme world (dark mode) | Done | portal container resolution in `theme-world.ts` (`getThemeContainer`, `data-theme-world="erp"`), `0dbd14f`; Gate 4 asserts dialog + listbox inside the ERP theme world in dark and light |

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

## Verification gate

Live stack: `skyrict-identity` (:8000) + `skyrict-core` (:8001) in Docker,
Postgres on host `:5433`, Next dev server `:3000`, Playwright 1.62.1.
Gate script: `pwshot/gates.js` (login with known MFA TOTP secrets, tour suppressed
via `localStorage["skyrict:product-tour-seen"]`).

| Gate | Check | Result |
|------|-------|--------|
| 1 | bridgeon HR home — KPI row renders; empty-state breakdown + activity | PASS (`Active employees=1, Open leave requests=0, On leave now=0, Departments=1`) |
| 6 | olympus HR home — populated KPIs (`3 / 1 / 1 / 2`); breakdown counts Pending/Approved/Rejected/Cancelled = 1 each; recent activity non-empty | PASS |
| 2 | Breakdown "Pending" click-through → `/erp/hr/leave?status=pending`; Leave status Select shows Pending | PASS |
| 3 | olympus payroll KPIs (`Payroll runs=5, Draft=1, Paid=1, Latest run=US$23,000.00`); runs breakdown Draft/Computed/Approved/Paid/Void = 1 each; recent runs show PR-5; "Draft" click-through → `/erp/payroll/runs?status=draft`; bridgeon payroll empty states | PASS |
| 4 | §7.4 — Dialog (dark), Select listbox (dark), Dialog (light) all render inside `[data-theme-world="erp"]` | PASS (`erp`) |
| 5 | §7.1/§7.2 — nav has `themed-scrollbar`; chevron inside active `rounded-lg` pill with no own `bg-` | PASS |
| — | No error banners on olympus pages (excluding Next.js route announcer) | PASS (`0 alerts`) |

Screenshots (all captured): `gate6-hr-home-bridgeon.png`, `gate6-hr-home-olympus.png`,
`gate2-leave-filtered.png`, `gate3-payroll-home-olympus.png`, `gate4-dialog-dark.png`,
`gate4-select-dark.png`, `gate4-dialog-light.png`, `gate5-sidebar-hover.png`.

Static gates on the §7 commits: `tsc --noEmit`, `eslint .`, and `next build`
green at the time of `aa7bfce`; no new repository dependencies.

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

`git log --oneline 44963eb..HEAD` = **4 commits**:

```
aa7bfce feat(web): [HR-UI-003 §7.3] HR and Payroll home overviews with click-through summaries
d334104 fix(web): [HR-UI-003 §7.1/§7.2] themed sidebar scrollbar + chevron inside row pill
0dbd14f fix(web): [HR-UI-003 §7.4] mount Radix portals inside the module-world wrapper
44963eb checkpoint: HR-UI-003 pre-§7 fixes (BFF, clients, sidebar, pages)
```
