# ERP Phase 1 — Core Modules (Architecture & Module Documentation)

## Status

Draft — approved scope. Targets the `core` service and the `starter` plan. Depends on the identity service (JWT verification, permissions, tenant context) and the billing gating work (SKY-32..36).

## Goal

Ship the "internal truth" half of the Skyrict Business Operating System as a **single backend service (`services/core`)** exposing five Phase-1 modules to the workspace:

1. **Finance & Accounting** — chart of accounts, journal entries, invoices (accounts receivable)
2. **Sales & CRM** — leads, opportunities, customers, sales orders
3. **Inventory & Warehouse** — products/items, stock levels, adjustments, transfers, reorder alerts
4. **HR & Payroll** — employees, leave, timesheets, payroll runs
5. **Reporting & Analytics** — cross-module dashboards, exports, scheduled snapshots

Every module is tenant-scoped, permission-gated, event-capable, and exposed through the same REST + BFF pattern the workspace already uses.

## Non-goals (Phase 1)

- Procurement / purchasing (depends on the same stock/order primitives; deferred)
- Production/manufacturing, multi-currency, consolidations, statutory filing
- Payroll *processing* (net-of-tax computation is external; we record pay runs and emit to a ledger)
- Replacing identity — `services/core` consumes, never re-implements, auth
- Kafka as a hard runtime dependency in Phase 1 (see "Events", below)

## Positioning

- `docs/architecture/readme.md` already slots ERP behind identity. This doc defines exactly what "ERP" means in Phase 1.
- The marketing pillars define the slice as "a deliberately scoped ERP slice — inventory, sales, cash, orders — … the ~20% of operations that 80% of SMBs actually use" (`apps/web/src/config/index.ts`). Phase 1 must stay in that band.
- `apps/web/src/config/onboarding.ts` already gates a **"Core ERP slice (inventory, sales, cash, orders)"** to the `starter` plan. Phase 1 maps the four named domains plus Finance/HR and Reporting as the Phase-1 module set.

## Architecture

### Service placement & repository

- New Python FastAPI service at **`services/core`**, added to the **uv workspace** (`pyproject.toml` workspace member) so it reuses `libs/skyrict-common`, `libs/skyrict-logging`, `libs/skyrict-events`.
- Name chosen for breadth: later modules (procurement, production, billing) land in the same service as new feature packages, not as new services. Spin off a service only when ownership, scaling, or event-boundary evidence demands it (see "Future").
- Mirror the **identity service's feature-based layout** (`services/identity/src/identity`) — not the `_template` scaffold. Each module is a self-contained **feature package**, with the framework wiring held once at the top level. Stack: Python 3.12, FastAPI, async SQLAlchemy 2, Alembic, pytest + factory-boy.

```
services/core/
├── src/core/
│   ├── api/
│   │   ├── deps.py          # auth / tenant / permission dependencies (shared)
│   │   ├── lifespan.py
│   │   ├── middleware.py
│   │   ├── readiness.py
│   │   └── v1/
│   │       ├── router.py    # mounts feature routers at /api/v1
│   │       └── health.py
│   ├── core/                # flat, cross-cutting (mirrors identity's core/):
│   │   │                    #   config, permissions, security, exceptions,
│   │   │                    #   constants, logging, telemetry, rate_limit,
│   │   │                    #   tenant_resolver, tenant_context, audit_events
│   │   └── ...
│   ├── db/                  # base, session, repository
│   ├── domain/              # entities, value_objects
│   ├── events/
│   │   ├── consumers/
│   │   ├── handlers/
│   │   └── producers/       # *_events.py per module
│   ├── features/            # one package per module (feature-based)
│   │   ├── finance/         #   models/, router.py, schemas.py,
│   │   ├── crm/             #   service.py, ports.py, repository.py
│   │   ├── inventory/
│   │   ├── hr/
│   │   └── reporting/
│   ├── cli.py               # ruff/lint/typecheck/test convenience targets
│   ├── main.py
│   └── seed.py              # reference data only
├── alembic/versions/        # 0001_initial + per-feature migrations
├── tests/{unit,integration,factories}
├── Dockerfile
└── pyproject.toml
```

### Feature package contract

Every module in `features/<module>/` follows the identity convention:

- `router.py` — FastAPI router with the feature's endpoints (mounted at `/api/v1/<module>` via `api/v1/router.py`); thin, delegates to the service.
- `schemas.py` — Pydantic request/response schemas (the API boundary).
- `service.py` — business rules; never touches SQLAlchemy directly, uses the repository + ports.
- `ports.py` — interfaces for dependencies the feature needs (e.g. finance posting, stock reservation, report queries); implementations live in the module or are injected.
- `repository.py` — SQLAlchemy data access; the **only** layer that queries/writes models. Holds the RLS/tenant scoping enforcement.
- `__init__.py` — optional feature exports/dependencies (mirrors `features/dependencies.py` pattern when features share deps).

### Layering contract (must hold)

- `api → features/<module>/service → repository → models`. Controllers stay thin; business rules live in the feature service; data access is centralized in the feature repository.
- **No direct DB access from API or event handlers.**
- Tenant scoping is enforced in the **repository layer** (see RLS), never trusted to caller discipline.
- `domain/entities.py` + `domain/value_objects.py` mirror identity's `domain/`; models implement domain shapes with SQLAlchemy, schemas are the API boundary.
- Money is a domain **value object** (`Money(amount: Decimal, currency: str)`) — never `float`.

### Configuration

- `src/core/core/config.py` mirrors identity's `core/config.py` pydantic-settings pattern (env prefix `CORE_`), reading from the shared `.env`.
- Required settings: `DATABASE_URL`, `JWT_PUBLIC_KEY`/`JWT_ISSUER` (same issuer as identity), `REDIS_URL` (optional in Phase 1 — used for lightweight caching/rate limiting), `KAFKA_BROKERS` (optional, see Events), `TENANT_HEADER` (default `X-Tenant-Slug`), `DEFAULT_CURRENCY` (`USD`).
- Versioned into the app via `app.state.settings` at lifespan, same pattern as identity.

### Multi-tenancy & isolation

- **Tenant model:** PostgreSQL 16 with **Row-Level Security (RLS)**. Every table carries a `tenant_id` (FK to identity's tenants, kept as an opaque UUID here), and every row is governed by a per-table RLS policy keyed to the session variable `app.current_tenant_id`.
- **Tenant resolution:** the `api/deps.py` dependency `get_tenant_context()` reads `X-Tenant-Slug`, resolves it to a tenant UUID via `core/tenant_resolver.py`, validates the token's membership, and sets `SET app.current_tenant_id = <tenant_id>` on the request session. Same request-scoped ContextVar pattern as identity (`core/tenant_context.py`).
- **Cross-tenant data:** impossible at the SQL level (RLS policy `USING (tenant_id = current_setting('app.current_tenant_id')::uuid)` on every table), so a missing or mismatched context returns 403, never a filtered-by-nothing query.
- **Table naming convention:** tenant-scoped tables use `erp_` prefix (e.g. `erp_products`, `erp_invoices`); reference tables that are globally seeded (e.g. `erp_currencies`, `erp_countries`) carry no tenant_id and are read-only.
- Multi-tenant indexes include `(tenant_id, …)` leading columns; every FK from tenant-scoped → tenant-scoped table includes `tenant_id` (composite FK) so RLS joins never leak.

### Authentication & authorization

- `services/core` is **stateless with respect to identity**: it verifies the identity-issued access JWT (same issuer/audience, key from `JWT_PUBLIC_KEY`), checks `sid` claim validity only at the BFF (identity already enforces revocation), and never mints its own tokens.
- **Permissions come from the JWT `permissions` claim** (identity already exposes `users/me/access` → `{roles, permissions}`). `core/core/permissions.py` keeps the ERP permission catalog and a `require_permission("erp.invoice.approve")` FastAPI dependency, mirroring `services/identity/src/identity/core/permissions.py`.
- **Session-scoped perms vs plan gating:** permission checks gate *who* can act; plan gating (from onboarding/billing) gates *whether the tenant has the module*. Both are enforced server-side; the sidebar filter is UI only.
- **Permissions the workspace already has** (`identity/core/permissions.py`): `erp.invoice.read`, `erp.invoice.approve`, `erp.purchase.approve`, plus `billing.manage`. Phase 1 **adds** the ERP permission keys below to the identity catalog (and to the seeded `tenant_owner`/`organization_admin`/`department_manager` role wiring) via a migration + seed update:

| Domain | Read | Write | Sensitive |
|---|---|---|---|
| Finance & Accounting | `erp.finance.read` | `erp.finance.write` | `erp.finance.approve` |
| Sales & CRM | `erp.sales.read` | `erp.sales.write` | `erp.sales.approve` |
| Inventory & Warehouse | `erp.inventory.read` | `erp.inventory.write` | `erp.inventory.approve` |
| HR & Payroll | `erp.hr.read` | `erp.hr.write` | `erp.hr.payroll.run` |
| Reporting & Analytics | `erp.reports.read` | — | — |

- **Role → permission mapping (proposed seed):** `tenant_owner` / `organization_admin` get all ERP permissions; `department_manager` gets `erp.inventory.*`, `erp.sales.*`, `erp.hr.read`; `standard_user` gets `erp.*.read`; `auditor` gets `erp.*.read` + `erp.reports.read`. Fine-grained per-user grants are configured in identity (Members) and enforced here.
- Every ERP mutation is **audited** via the identity audit integration (module `core`, action, resource id, actor, tenant).

### Events

- `libs/skyrict-events` (`src/skyrict_events/base.py`) defines the envelope: `{event_id, event_type, timestamp, tenant_id, version, correlation_id, metadata}` with topic convention **`{domain}.{entity}.{action}`**.
- **Phase 1 policy:** emit events only; do not require Kafka to serve a request. Producers publish in-process when `KAFKA_BROKERS` is set and no-op otherwise; any consumer (reporting refresh, e.g.) is an **outbox-polled or background-job** subscriber in Phase 1. Hard Kafka adoption lands with a dedicated async boundary (see "Future").
- Events are emitted from **services, after commit**, using the BaseEvent envelope, keyed by `tenant_id`.
- Reserved topics already named in the lib: `finance.journal_entry.posted`, `inventory.stock.level_changed`. Proposed Phase-1 additions:

| Topic | Emitted by | Consumer intent |
|---|---|---|
| `finance.journal_entry.posted` | Finance service | Reporting refresh, cash-flow feed (reserved) |
| `inventory.stock.level_changed` | Inventory service | Reorder alerts, reporting (reserved) |
| `sales.order.confirmed` | Sales service | Inventory reservation, reporting |
| `crm.lead.status_changed` | CRM service | Reporting, agent hooks |
| `hr.employee.onboarded` | HR service | Payroll eligibility, reporting |
| `reporting.snapshot.refreshed` | Reporting service | Dashboard invalidation |

### Error handling, pagination, idempotency

- Reuse `skyrict-common` (RFC 7807 `application/problem+json` error envelope, validation error shape). `core/core/exceptions.py` mirrors identity.
- Pagination is cursor-based (`limit`, `cursor`) for list endpoints; page metadata is part of the list envelope (`{items, next_cursor, total}`), matching identity's list responses.
- **Idempotency keys** on mutating financial/order endpoints (`Idempotency-Key` header, stored with TTL) so retries of `POST` (invoice approval, stock adjustment, payroll run) never double-apply.

### Migrations

- Alembic under `services/core/alembic/`. Migration `0001_initial` creates all Phase-1 tables + indexes + **RLS policies**; subsequent migrations are per-feature.
- RLS policies and `tenant_id` columns are part of the schema, reviewed in the same PR as the models.
- Seed (`src/core/seed.py`, same position as identity's `seed.py`): reference data only (`erp_currencies`, `erp_countries`, a starter chart-of-accounts template, payment terms). No tenant data in seeds — fixtures cover that.

## Module Deep-Dives

Each module is a feature package under `src/core/features/<module>/` (`router.py`, `schemas.py`, `service.py`, `ports.py`, `repository.py`) with its model files in `features/<module>/models/` (one file per table) and event producers in `src/core/events/producers/`. All endpoints are prefixed `/api/v1/<module>`, require a valid access JWT + tenant context, and check the listed permissions server-side.

### M-FIN — Finance & Accounting

**Purpose.** The books of record: chart of accounts, double-entry journal entries, and accounts receivable. Feeds every reporting view; is the downstream of sales orders and payroll runs.

**Entities.** `erp_chart_of_accounts` (code, name, type: asset/liability/equity/revenue/expense, is_active), `erp_journal_entries` (date, memo, status: draft/posted, source, source_ref) + `erp_journal_lines` (account, debit, credit, Money), `erp_invoices` (customer, number, issue_date, due_date, status: draft/sent/partial/paid/written_off, Money) + `erp_invoice_lines`, `erp_payments` (invoice_id, amount, method, received_at).

**Rules (service layer).**
- A journal entry is balanced (Σ debit == Σ credit) and immutable once `posted`.
- Invoicing auto-generates the `accounts_receivable` / `sales_revenue` journal lines on posting.
- Payments apply to an invoice in FIFO of `due_date`; overpayment opens a credit balance.
- `Money` arithmetic is Decimal; currency is validated against `erp_currencies`.

**Endpoints (draft).**
- `GET/POST /api/v1/finance/chart-of-accounts` (`erp.finance.read` / `.write`)
- `GET/POST /api/v1/finance/journal-entries` (.read/.write), `POST .../{id}/post` (`erp.finance.approve`)
- `GET/POST /api/v1/finance/invoices`, `POST .../{id}/approve` (`erp.finance.approve`), `POST .../{id}/payments`, `GET .../{id}`

**Events.** `finance.journal_entry.posted`.

**Acceptance criteria.** Balanced-only posting enforced; RLS isolates tenants; idempotent approval; payment reduces invoice balance and emits the entry event; audit rows written for approve/pay.

### M-CRM — Sales & CRM

**Purpose.** Pipeline and customer relationships: leads → opportunities → customers, plus the sales orders that hand off to inventory and finance.

**Entities.** `erp_leads` (source, status: new/contacted/qualified/lost), `erp_opportunities` (lead_id, stage: qualification/proposal/negotiation/won/lost, amount, expected_close_date, owner_id), `erp_customers` (name, email, phone, tax_id, payment_terms, credit_limit), `erp_sales_orders` (customer_id, status: draft/confirmed/fulfilled/cancelled, order_date, Money) + `erp_sales_order_lines` (item_id, qty, unit_price, Money).

**Rules.**
- Winning an opportunity can promote it to a customer; confirmation of an order emits `sales.order.confirmed` (inventory reservation is a Phase-1 async/outbox subscriber or direct service call within `core`).
- Credit-limit check on order confirmation for `on_credit` terms.
- `owner_id` references identity users; owners see their own pipeline, managers see the team (server-side filter).

**Endpoints (draft).**
- `GET/POST /api/v1/crm/leads`, `PATCH .../{id}/status`
- `GET/POST /api/v1/crm/opportunities`, `PATCH .../{id}/stage`
- `GET/POST /api/v1/crm/customers`
- `GET/POST /api/v1/crm/sales-orders`, `POST .../{id}/confirm` (`erp.sales.approve`), `POST .../{id}/fulfil` (creates invoice via Finance service)

**Events.** `crm.lead.status_changed`, `sales.order.confirmed`.

**Acceptance criteria.** Pipeline metrics computed from staged opportunities; order confirmation is idempotent and produces exactly one invoice + stock effect; owner scoping enforced server-side.

### M-INV — Inventory & Warehouse

**Purpose.** Stock as operational truth: products, current quantity, movements, and reorder alerts. The named "inventory" pillar of the marketing slice.

**Entities.** `erp_products` (sku, name, category, unit, cost_price, sell_price, reorder_point, is_active), `erp_warehouses` (name, location, is_active), `erp_stock_levels` (product_id, warehouse_id, qty_on_hand, qty_reserved), `erp_stock_movements` (product_id, warehouse_id, type: receive/adjust/transfer/sale/return, qty, ref_type, ref_id, occurred_at, reason).

**Rules.**
- Stock is a **ledger**, not a stored mutable counter: every change is an `erp_stock_movements` row; `qty_on_hand` is the derived sum (materialized in `erp_stock_levels` for reads, recomputed on movement, or via materialized view — decision recorded in ADR-000 core, default to recompute-on-write for Phase 1).
- `qty_on_hand` never goes negative; transfers are two movements (source −, destination +) in one transaction.
- Sale/order fulfilment and returns hook here; adjustment requires a `reason` and `erp.inventory.approve` when the delta exceeds a threshold (configurable).
- Reorder alert when `qty_on_hand ≤ reorder_point` → emits `inventory.stock.level_changed` and surfaces in Reporting.

**Endpoints (draft).**
- `GET/POST /api/v1/inventory/products`, `GET/POST /api/v1/inventory/warehouses`
- `GET /api/v1/inventory/stock` (per product/warehouse)
- `POST /api/v1/inventory/stock/adjustments` (`erp.inventory.write`, large deltas `.approve`), `POST /api/v1/inventory/stock/transfers`, `GET /api/v1/inventory/stock/movements`
- `GET /api/v1/inventory/alerts` (reorder-point breaches)

**Events.** `inventory.stock.level_changed`.

**Acceptance criteria.** No negative stock; movements immutable; transfer is atomic; reorder alerts fire once per breach crossing; per-warehouse isolation and tenant isolation verified.

### M-HR — HR & Payroll

**Purpose.** People truth: employees, leave, timesheets, and the pay-run records that hand to Finance. Payroll here is **records + approval**, not tax computation.

**Entities.** `erp_employees` (user_id, employee_no, department, job_title, hire_date, status: active/terminated, salary, currency, tax_id), `erp_leave_requests` (employee_id, type, from, to, status: requested/approved/rejected, balance), `erp_leave_balances` (employee_id, type, year, accrued, used), `erp_timesheets` (employee_id, period_start, period_end, total_hours, status), `erp_payroll_runs` (period, status: draft/approved/paid, currency, total) + `erp_payroll_entries` (run_id, employee_id, gross, deductions, net, Money).

**Rules.**
- Leave approval gates on remaining balance (`erp.leave.approve` equivalent → reuse `erp.hr.write` in Phase 1 unless an explicit approve key is wanted; keep `erp.hr.payroll.run` separate).
- Payroll run computes gross from salary/timesheets, applies configured deductions, produces entries, and posts the payroll expense journal entry (Finance) on approval.
- PII discipline: `tax_id` encrypted at rest (reuse identity's field-level encryption approach); employee records are tenant-scoped.

**Endpoints (draft).**
- `GET/POST /api/v1/hr/employees`, `PATCH .../{id}/status`
- `GET/POST /api/v1/hr/leave/requests`, `POST .../{id}/approve|reject`
- `POST /api/v1/hr/timesheets`, `GET /api/v1/hr/timesheets`
- `GET/POST /api/v1/hr/payroll/runs`, `POST .../{id}/approve` (`erp.hr.payroll.run`), `POST .../{id}/post` (→ Finance journal entry)

**Events.** `hr.employee.onboarded`.

**Acceptance criteria.** Leave balance never over-drawn; payroll run is idempotent and posts exactly one journal entry; terminated employees cannot be included in a new run; PII fields never appear in list payloads by default.

### M-RPT — Reporting & Analytics

**Purpose.** The cross-module synthesis the workspace is built around: dashboards, exports, and scheduled snapshots consumed by the agent layer and the workspace UI.

**Entities.** `erp_report_definitions` (slug, title, module, sql/dataset ref, params), `erp_report_snapshots` (definition_id, period, payload jsonb, generated_at), `erp_dashboards` (title, layout jsonb, tenant_default flag).

**Reporting view (concrete Phase-1 set).**
- **Financial:** P&L by period, AR aging, cash received
- **Sales/CRM:** pipeline value by stage, orders by period, top customers
- **Inventory:** stock on hand vs reorder point, movement by type, slow movers
- **HR:** headcount by department, leave usage, payroll cost by period

**Rules.**
- Views are SQL materialized via a thin query layer (parameterized, tenant-filtered, **read-only**), never raw SQL passed from clients.
- Snapshots are stored (`erp_report_snapshots`) for trend/backfill and scheduled refresh (outbox/background job in Phase 1).
- CSV/JSON export is generated server-side and streamed; exports are audited.

**Endpoints (draft).**
- `GET /api/v1/reporting/dashboard` (default tenant dashboard), `PUT /api/v1/reporting/dashboard` (layout)
- `GET /api/v1/reporting/{definition_slug}?from=&to=`, `GET /api/v1/reporting/{definition_slug}/export.csv`
- `POST /api/v1/reporting/snapshots` (manual refresh), `GET /api/v1/reporting/snapshots/{id}`

**All endpoints:** `erp.reports.read`.

**Events.** `reporting.snapshot.refreshed`.

**Acceptance criteria.** Every report returns the tenant's data only (verified with two tenants in integration tests); snapshot refresh is idempotent per (definition, period); exports match the API payload row-for-row.

## Cross-Cutting

### Tenancy & isolation rules (summary)

1. Every `erp_*` table: `tenant_id` + RLS policy + composite FK where applicable.
2. Tenant context comes from the validated JWT + `X-Tenant-Slug`; never from a query param.
3. No cross-tenant reads/writes possible at the SQL layer; tests assert isolation on the money-critical tables (journal lines, stock movements, payroll entries).
4. Tenant-wide "deletion" is soft (is_active), not hard DELETE, for financial/order records.

### Audit

- All ERP mutations write an audit event via the shared audit integration: `{actor, tenant, module, action, resource_type, resource_id, at}`.
- Sensitive operations additionally require step-up (re-auth) at the BFF: invoice approve, payroll run approve, large stock adjustments, report export of PII-bearing HR data.

### Frontend integration (workspace)

- Sidebar group **ERP** at `apps/web/src/app/(workspace)/dashboard/erp` with per-module sections (Finance, Sales, CRM, Inventory, HR, Reports). Sidebar filter keys: `erp.finance.read`, `erp.sales.read`, `erp.inventory.read`, `erp.hr.read`, `erp.reports.read` — UI only; all enforcement is server-side.
- Generated client: add `services/core` OpenAPI schema to the API-client codegen (same pipeline as identity). BFF route handlers in the web app proxy `/api/erp/*` same-origin, origin-checked, `no-store`, mirroring the existing auth BFF discipline.
- Plan gating: module visibility for a tenant comes from billing state (`starter` → Core ERP slice). BFF merges `permissions` (JWT) × `enabled_modules` (billing) before responding.

### Service API surface discipline

- All responses JSON; errors RFC 7807 `problem+json`; list responses cursor-paginated; mutating financial/order endpoints accept `Idempotency-Key`.
- OpenAPI generated at build; contract-tested against the workspace client.

## Infra & CI

- **Local:** add `core` to `docker-compose` (uv-managed, hot-reload) reusing the existing Postgres 16 + Redis; add `core.*.localhost` dev hosts. Kafka stays optional.
- **CI:** new workflow `ci-core.yml` modeled on `ci-identity.yml`: `uv sync --frozen` → `ruff check` → `mypy`/`pyright` → `pytest` (unit + integration, with RLS-enabled Postgres) → Docker build. gating `make core-lint`, `make core-test` (mirroring existing Makefile targets) and `make core-check` (ruff + format-check + typecheck + test).
- **CD:** deploy `core` alongside identity; k8s overlay adds a `core` Deployment/Service; wildcard TLS already covers new subdomains (ADR-003).
- **Makefile targets (proposed):** `core-up`, `core-lint`, `core-test`, `core-check`, `core-migrate`.

## Dependencies & Sequencing

Phase 1 ERP is **blocked by** (tracked in Jira):

- **SKY-30 / SKY-31** — identity service hardening + workspace routing that the BFF/tenant/session story depends on.
- **SKY-32 … SKY-36** — onboarding/billing gating: without `enabled_modules`, plan-based visibility of ERP modules cannot be enforced server-side.

Internal sequencing (single track, after the above):

1. **M3 skeleton** — `services/core` scaffold, RLS migration, tenant/JWT deps, permission catalog, contract tests. (ADR for RLS-ledger decision + money value object.)
2. **M-INV** first (highest operational value; the "inventory" pillar).
3. **M-CRM** (sales orders reference products).
4. **M-FIN** (invoices consume sales orders; AR pays).
5. **M-HR** (payroll posts to finance).
6. **M-RPT** last (consumes all four; the "synthesis" layer).
7. **BFF + workspace UI + plan gating** in parallel with 2–6.
8. **E2E verification** across two tenants asserting isolation on money-critical tables.

## Future (explicitly out of Phase 1)

- Procurement & purchasing (reuses stock/order primitives; `erp.purchase.approve` key already exists in identity).
- Hard Kafka async boundary — adopt when reporting/agent consumers require real decoupling; until then, in-process + outbox/background job is the contract.
- Billing service extraction if invoice lifecycles outgrow `core`; new modules join `core` as feature packages first.
- The agent layer consumes ERP events + report snapshots (Phase-2+ bridge, out of this doc).

## Related

- `docs/architecture/readme.md`, `docs/architecture/auth-production-model.md`, ADR-001 (uv workspaces), ADR-002 (single identity service), ADR-003 (staging wildcard DNS/TLS), ADR-004 (login security posture)
- `libs/skyrict-common`, `libs/skyrict-logging`, `libs/skyrict-events` (`src/skyrict_events/base.py`)
- `services/identity` (feature-based structure reference; auth/permissions/tenant source of truth)
- `apps/web/src/config/onboarding.ts` (starter plan → Core ERP slice), `apps/web/src/config/index.ts` (pillars)
- Jira: SKY-30/31 (identity), SKY-32..36 (billing gating), SKY-40+ (ERP Phase 1 track)
