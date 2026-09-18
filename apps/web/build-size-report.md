# Skyrict Web — Bundle Size Baseline & Performance Budget

Committed baseline for the frontend performance gate (PERF-WEB-001).

## Method

- **Source**: a production `next build` of `apps/web` (App Router, webpack), route table printed by Next.
- **Metric**: **First Load JS (gzip)** per route, as reported by Next's build output. Shared-by-all chunk total is the "first load JS shared by all" figure. Both are gzip, identical units to what Lighthouse consumes on the wire.
- **Generated**: 2026-09-18, HEAD `82f43f5b`, Next 15.5.24 / React 19, `ANALYZE=true` build (Sentry wrapper active).
- **Machine baseline**: `perf-baseline.json` (93 routes, shared total, top chunks) — the CI budget gate compares against this file, so it must stay in sync with any committed change to this report.

## Headline numbers

| Metric | gzip |
|---|---:|
| First Load JS **shared by all routes** | **161 kB** |
| `/dashboard` (post-login home) | 186 kB |
| `/dashboard/erp/reports` | 192 kB |
| `/dashboard/erp/inventory/health` | 303 kB |
| `/dashboard/erp/payroll` | **307 kB** |

The ERP surface is the heaviest: `/payroll` at 307 kB and `/inventory/health` at 303 kB first-load JS are the two largest key routes; both pull in recharts and the full shell chrome on first paint.

## Budget (enforced in CI)

| Route | First Load JS budget (gzip) |
|---|---:|
| all routes (shared) | ≤ 161 kB |
| `/dashboard` | ≤ 186 kB |
| `/dashboard/erp/reports` | ≤ 192 kB |
| `/dashboard/erp/inventory/health` | ≤ 303 kB |
| `/dashboard/erp/payroll` | ≤ 307 kB |

Strict monotonic: the gate fails if any budgeted route **exceeds** the committed baseline. The gate (`scripts/perf/assert-bundle-sizes.mjs` in `ci-web.yml`) enforces **every route in the table below** at its baseline value — the rows above are the headline targets. Improvements are expected to lower these numbers; when a change deliberately moves one up, the baseline file + this report are updated **in the same commit**.

## Largest client chunks (gzip)

| Chunk | gzip |
|---|---:|
| `7543-e2ba7afff10f9ff8.js` | 100.6 kB |
| `9867-006efd5e1f2f4d22.js` | 100.1 kB |
| `framework-d61c2e59fbde7661.js` | 58.4 kB |
| `7be59ca9-c25671d35b808af5.js` | 53.1 kB |
| `pages/_app-24926e39eb296963.js` | 50.5 kB |
| `5311-0aea1e9f5e26f0b8.js` | 36.7 kB |
| `5916-3dff8b9c37ca6543.js` | 36.3 kB |
| `main-b593a79d04c3e94a.js` | 35.8 kB |
| `8648-8c529a4f5aa6614b.js` | 28.4 kB |

Two ~100 kB chunks dominate the shared budget; the total first-load `161 kB` shared baseline is exactly their sum plus framework/main. These are the target for the ShellRouter code-split and chart isolation workstreams.

## Full route table (all 93 routes)

| Route | Size | First Load JS (gzip) |
|---|---:|---:|
| /dashboard | 8.05 kB | 186 kB |
| /dashboard/agents/coaching | 4.13 kB | 158 kB |
| /dashboard/agents/guardian | 3.96 kB | 157 kB |
| /dashboard/agents/guardian/[reportId] | 4.47 kB | 156 kB |
| /dashboard/agents/c/[id] | 2.86 kB | 155 kB |
| /dashboard/erp | 10.1 kB | 169 kB |
| /dashboard/erp/approvals | 7.99 kB | 176 kB |
| /dashboard/erp/crm/ai | 5.2 kB | 182 kB |
| /dashboard/erp/crm/contacts | 6.62 kB | 179 kB |
| /dashboard/erp/crm/customers | 8.05 kB | 183 kB |
| /dashboard/erp/crm/customers/[customerId] | 7.42 kB | 183 kB |
| /dashboard/erp/crm/leads | 7.44 kB | 183 kB |
| /dashboard/erp/crm/leads/[leadId] | 8.56 kB | 184 kB |
| /dashboard/erp/crm/opportunities | 7.57 kB | 184 kB |
| /dashboard/erp/crm/opportunities/[opportunityId] | 8.25 kB | 185 kB |
| /dashboard/erp/crm/search | 7.57 kB | 184 kB |
| /dashboard/erp/documents | 5.6 kB | 159 kB |
| /dashboard/erp/documents/[id] | 5.58 kB | 159 kB |
| /dashboard/erp/documents/list | 5.76 kB | 159 kB |
| /dashboard/erp/finance/accounts | 5.73 kB | 168 kB |
| /dashboard/erp/finance/ai-docs | 6.38 kB | 169 kB |
| /dashboard/erp/finance/audit-log | 7.28 kB | 170 kB |
| /dashboard/erp/finance/budgets | 4.59 kB | 166 kB |
| /dashboard/erp/finance/compliance | 4.59 kB | 166 kB |
| /dashboard/erp/finance/controls | 7.73 kB | 172 kB |
| /dashboard/erp/finance/expenses | 4.59 kB | 166 kB |
| /dashboard/erp/finance/fiscal-periods | 5.75 kB | 168 kB |
| /dashboard/erp/finance/invoices | 5.24 kB | 167 kB |
| /dashboard/erp/finance/invoices/[id] | 7.13 kB | 169 kB |
| /dashboard/erp/finance/journal-entries | 5.73 kB | 168 kB |
| /dashboard/erp/finance/journal-entries/[id] | 7.04 kB | 170 kB |
| /dashboard/erp/finance/statements | 7.47 kB | 170 kB |
| /dashboard/erp/hr/ai-alerts | 6.36 kB | 175 kB |
| /dashboard/erp/hr/attendance | 8.36 kB | 178 kB |
| /dashboard/erp/hr/attrition | 5.5 kB | 174 kB |
| /dashboard/erp/hr/compliance | 7.45 kB | 176 kB |
| /dashboard/erp/hr/correlation | 4.58 kB | 170 kB |
| /dashboard/erp/hr/data-quality | 5.88 kB | 174 kB |
| /dashboard/erp/hr/departments | 7.05 kB | 176 kB |
| /dashboard/erp/hr/employees | 5.37 kB | 173 kB |
| /dashboard/erp/hr/employees/[id] | 5.85 kB | 174 kB |
| /dashboard/erp/hr/leave | 8.25 kB | 178 kB |
| /dashboard/erp/hr/planning | 8.94 kB | 180 kB |
| /dashboard/erp/inventory/abc | 6.13 kB | 214 kB |
| /dashboard/erp/inventory/alerts | 4.65 kB | 234 kB |
| /dashboard/erp/inventory/anomalies | 6.45 kB | 178 kB |
| /dashboard/erp/inventory/forecast | 6.94 kB | 215 kB |
| /dashboard/erp/inventory/health | 4.06 kB | **303 kB** |
| /dashboard/erp/inventory/movements | 6.84 kB | 215 kB |
| /dashboard/erp/inventory/products | 7.52 kB | 215 kB |
| /dashboard/erp/inventory/stock | 5.37 kB | 237 kB |
| /dashboard/erp/inventory/suggestions | 6.18 kB | 178 kB |
| /dashboard/erp/inventory/suppliers | 6.21 kB | 180 kB |
| /dashboard/erp/inventory/warehouses | 6.67 kB | 213 kB |
| /dashboard/erp/orders | 7.07 kB | 239 kB |
| /dashboard/erp/orders/[orderId] | 5.01 kB | 218 kB |
| /dashboard/erp/payroll | 6.54 kB | **307 kB** |
| /dashboard/erp/payroll/anomalies | 6.08 kB | 190 kB |
| /dashboard/erp/payroll/automation | 12.4 kB | 198 kB |
| /dashboard/erp/payroll/compensation | 9 kB | 226 kB |
| /dashboard/erp/payroll/reviews | 8.59 kB | 204 kB |
| /dashboard/erp/payroll/runs | 9.1 kB | 219 kB |
| /dashboard/erp/payroll/runs/[id] | 12 kB | 219 kB |
| /dashboard/erp/payroll/settings | 9.91 kB | 194 kB |
| /dashboard/erp/payroll/void-reasons | 7.71 kB | 189 kB |
| /dashboard/erp/reports | 6.35 kB | 192 kB |
| /dashboard/erp/reports/[reportId] | 8.93 kB | 315 kB |
| /dashboard/erp/sales | 4.08 kB | 161 kB |
| /dashboard/intelligence | 4.8 kB | 177 kB |
| /dashboard/intelligence/explore | 4.62 kB | 164 kB |
| /dashboard/intelligence/feedback | 4.17 kB | 163 kB |
| /dashboard/intelligence/helpdesk | 3.05 kB | 162 kB |
| /dashboard/intelligence/market | 4.69 kB | 164 kB |
| /dashboard/intelligence/results | 6.69 kB | 178 kB |
| /dashboard/intelligence/trending | 4.15 kB | 164 kB |
| /dashboard/invite | 7.58 kB | 217 kB |
| /dashboard/leave | 8.53 kB | 217 kB |
| /dashboard/members | 7.17 kB | 220 kB |
| /dashboard/roles | 8.14 kB | 200 kB |
| /dashboard/settings | 8.35 kB | 197 kB |
| /dashboard/settings/notifications | 6.64 kB | 177 kB |
| /intelligence | 0.451 kB | 161 kB |
| /invite | 7.47 kB | 210 kB |
| /login | 6.37 kB | 212 kB |
| /mfa/verify | 4.1 kB | 181 kB |
| /privacy | 0.451 kB | 161 kB |
| /register | 7.4 kB | 215 kB |
| /register/organization | 15.8 kB | 256 kB |
| /register/plan | 5.56 kB | 195 kB |
| /register/security | 10.7 kB | 213 kB |
| /register/verify | 6.06 kB | 183 kB |
| /setup-mfa | 12.2 kB | 189 kB |
| /terms | 0.451 kB | 161 kB |

## Regeneration

```bash
cd apps/web
ANALYZE=true next build > build.log 2>&1   # or pnpm analyze:next
node scripts/perf/parse-bundle-sizes.mjs --log build.log --analyze .next/analyze/client.html > scripts/perf/perf-baseline.json
# update budget rows above + commit both files together
```

The CI gate does not need the analyzer: `ci-web.yml` runs a plain `next build`,
then `node scripts/perf/assert-bundle-sizes.mjs --log build.log` against the
committed `scripts/perf/perf-baseline.json`.