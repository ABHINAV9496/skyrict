# M-RPT - Reporting Data Layer (RPT-DATA-001)

> **Status:** Implemented. Target: `services/core`.
> **Owner:** Skyrict engineering (SKY-77 / RPT-DATA-001).
> **Spec:** `docs/architecture/erp-phase1.md` §M-RPT.
> **Permission:** `erp.reports.read` for every report definition and snapshot read.

This document defines the **first link of the reporting chain**: the tenant data layer
(``erp_report_definitions`` + ``erp_report_snapshots``), the seed pack that populates it,
and the read-only SQL contract enforced before anything is persisted. Downstream
consumers (the workspace UI, the agent layer, CSV/JSON export, scheduled snapshots) read
these tables; they do not define them.

---

## 1. Overview

Reporting is a **cross-module synthesis** — a P&L row reads `erp_journal_lines`, an
AR-aging row reads `erp_invoices` + `erp_payments`, a headcount row reads
`erp_departments` + `erp_employees`. That breadth is exactly why the data layer exists:
report definitions and their materialized results get a single, tenant-scoped home instead
of ad-hoc query spread across modules.

**The one idea to internalize: reports are code, snapshots are data.** A definition is a
per-tenant, versioned, read-only SQL statement with a declared parameter whitelist. A
snapshot is the rendered output for one `(definition, period)` — immutable, idempotently
refreshable.

**Consumers of this data layer (built in later phases):**
- **RPT-BE (backfill/export):** runs definitions, writes snapshots, streams CSV/JSON.
- **RPT-DASH:** the workspace dashboard reads snapshots; definitions power the report picker.
- **Agent layer:** consumes snapshots as ground truth for questions ("what was payroll in Q3?").

---

## 2. Scope

### 2.1 In scope (this ticket)
- `erp_report_definitions` and `erp_report_snapshots` tables (UUID PK, soft/RESTRICT-free,
  audit columns, RLS).
- The Phase-1 report pack (12 definitions) seeded into every tenant — both existing
  tenants (migration 0036) and newly provisioned tenants (`core.seed`).
- The `erp.reports.read` permission, seeded and catalogued.
- The read-only SQL validator (`core.features.reporting.validation`).
- The `ReportRepository` snapshot/definition access (`core.features.reporting.repository`).

### 2.2 Out of scope (Phase 1 / later tickets)
- The report runner / query execution layer (RPT-BE).
- Endpoints under `/api/v1/reporting/*` (draft in erp-phase1.md §M-RPT).
- Dashboard layout work (`erp_dashboards` — already shipped, SKY-62).
- Scheduled snapshot refresh / outbox jobs.

---

## 3. Data model

Tables are in `services/core`, registered in `alembic/env.py`, migrated under
`alembic_version_core`. Both tables share the standard mechanics: `tenant_id` UUID PK
FK → `tenants.id` ON DELETE CASCADE, `id` UUID PK `gen_random_uuid()`, `created_at` /
`updated_at` timestamptz with `server_default now()`, and the
`tenant_isolation_<table>` RLS policy on `tenant_id = public.current_tenant_id()`.

### 3.1 `erp_report_definitions` — the per-tenant report catalog

| Column | Type / Constraint | Why it exists |
|---|---|---|
| `tenant_id` | UUID, NOT NULL | Ownership + RLS key |
| `slug` | String(64), NOT NULL | Stable machine name (`pnl_by_period`). **Unique per tenant**: `UNIQUE (tenant_id, slug)` named `uq_erp_report_definitions_tenant_slug` |
| `title` | String(255), NOT NULL | Human name ("P&L by period") |
| `module` | String(32), NOT NULL | Owning module: `finance` / `sales` / `inventory` / `hr` |
| `description` | Text, nullable | What the report answers |
| `sql` | Text, NOT NULL | The dataset query. Must satisfy the read-only contract (§5) |
| `params` | JSONB, NOT NULL default `[]` | Allow-list of `:name` bind parameters the query may use |
| `permission_key` | String(64), NOT NULL default `erp.reports.read` | Gates serving this definition |
| `version` | Integer, NOT NULL default 1 | Bumped when the query changes |
| `is_active` | Boolean, NOT NULL default `true` | Soft-deactivate a definition — definitions are versioned, never hard-deleted |

Index: `ix_erp_report_definitions_tenant_module` (`tenant_id`, `module`).

### 3.2 `erp_report_snapshots` — materialized report results

| Column | Type / Constraint | Why it exists |
|---|---|---|
| `tenant_id` | UUID, NOT NULL | Ownership + RLS key |
| `definition_id` | UUID, NOT NULL | Composite FK `(tenant_id, definition_id)` → `erp_report_definitions(tenant_id, id)` ON DELETE CASCADE, named `fk_erp_report_snapshots_definition` — a snapshot can only reference a definition in the same tenant |
| `period` | Date, NOT NULL | The period the snapshot answers (e.g. `2026-09-01` for September) |
| `payload` | JSONB, NOT NULL default `[]` | The rendered rows (list of row objects) |
| `schema_version` | Integer, NOT NULL default 1 | Payload shape version for readers |
| `generated_at` | timestamptz, NOT NULL default now(), `onupdate now()` | When the payload was last rendered |

**Uniqueness (the idempotency lock):** `UNIQUE (tenant_id, definition_id, period)` named
`uq_erp_report_snapshots_tenant_definition_period` — re-running a period **replaces** the
payload, never duplicates it (§M-RPT acceptance).

Index: `ix_erp_report_snapshots_tenant_period` (`tenant_id`, `period`).

---

## 4. Seeding the catalog — one source of truth

The 12-report pack lives in exactly one place: `core.features.reporting.seeds`
(`PHASE_1_REPORT_SEEDS`). Two call sites consume it — they never duplicate it:

1. **Migration 0036** — after creating the tables, for **every tenant that already
   exists**, it inserts the pack via `INSERT ... SELECT t.id, ... FROM tenants t
   ON CONFLICT (tenant_id, slug) DO NOTHING`.
2. **`core.seed.seed_reporting_defaults(tenant_id)`** — tenant provisioning. The CLI
   `core seed --tenant-id <id>` applies HR defaults, the reporting pack, and RBAC roles.

Both call sites **validate every seed's SQL read-only before inserting** and skip
existing slugs, so a newly provisioned tenant is indistinguishable from one that
pre-dates 0036.

### 4.1 The Phase-1 pack (erp-phase1.md §M-RPT reporting view)

| Slug | Module | Parameters |
|---|---|---|
| `pnl_by_period` | finance | `tenant_id`, `from_date`, `to_date` |
| `ar_aging` | finance | `tenant_id`, `as_of_date` |
| `cash_received` | finance | `tenant_id`, `from_date`, `to_date` |
| `pipeline_value_by_stage` | sales | `tenant_id` |
| `orders_by_period` | sales | `tenant_id`, `from_date`, `to_date` |
| `top_customers` | sales | `tenant_id` |
| `stock_on_hand_vs_reorder` | inventory | `tenant_id` |
| `movement_by_type` | inventory | `tenant_id`, `from_date`, `to_date` |
| `slow_movers` | inventory | `tenant_id`, `from_date`, `to_date` |
| `headcount_by_department` | hr | `tenant_id` |
| `leave_usage` | hr | `tenant_id`, `from_date`, `to_date` |
| `payroll_cost_by_period` | hr | `tenant_id`, `from_date`, `to_date` |

Every definition carries `permission_key = erp.reports.read`.

---

## 5. The read-only SQL contract

`core.features.reporting.validation.validate_read_only_sql(sql, allowed_params) -> set[str]`
(no external parser dependency — a small, tested lexical scanner) enforces:

- **Single statement, SELECT only.** Leading comments/whitespace are stripped; the first
  keyword must be `SELECT` (a leading `WITH`/CTE is rejected; nested `SELECT` subqueries
  in `FROM` are fine); `;` anywhere is rejected (multi-statement).
- **No write or session keywords anywhere** — DML, DDL, privilege statements, transaction
  control (`BEGIN`/`COMMIT`/`ROLLBACK`), `SELECT ... INTO`, etc.
- **Named binds only from the whitelist.** `:name` params are extracted, `::` casts
  skipped; an undeclared bind raises. `params` must match the binds used (tight whitelist
  — enforced by the catalog test).
- **Lexical honesty.** Keywords inside string literals, comments, and dollar-quoted
  strings are ignored; unterminated literals are rejected.

Validation happens **before any insert** in both call sites — a bad definition aborts the
migration upgrade or the provisioning seed (fail closed, atomic).

---

## 6. Repository access

`core.features.reporting.repository.ReportRepository`:

- `list_active_definitions(tenant_id)` / `get_definition(tenant_id, slug)`
- `upsert_snapshot(tenant_id, definition_id, period, payload)` — idempotent per the
  unique constraint; replaces `payload` + refreshes `generated_at` when the period exists
- `get_snapshot(tenant_id, definition_id, period)`

---

## 7. Security

- **RLS** is the enforcement layer, not an afterthought: `tenant_isolation_erp_report_*`
  policies keyed on `public.current_tenant_id()`. Even if a runner drops a tenant filter,
  the boundary holds — verified in integration tests via a non-owner role.
- **Cross-tenant snapshots are impossible at the schema level**: the composite FK
  `(tenant_id, definition_id)` has no valid row across tenants, so the write fails even
  as the table owner.
- **No raw client SQL**: definitions are server-authored seeds; clients only reference
  them by slug and provide whitelisted parameters.

## 8. Acceptance criteria (from erp-phase1.md §M-RPT)

- ✅ Every report returns the tenant's data only — two-tenant RLS integration tests.
- ✅ Snapshot refresh idempotent per `(definition, period)` — unique constraint +
  repository replace-on-write tests.
- ⏳ Exports match the API payload row-for-row — RPT-BE ticket (out of scope here).