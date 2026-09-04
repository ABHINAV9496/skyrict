# M-FIN - Finance & Accounting Module (Phase 1)

> **Status:** Draft - approved scope. Target: `services/core`, starter plan.
> **Owner:** Dennis
> **Dependencies:** identity service (JWT verification, permissions, tenant context), `services/core` skeleton ([ERP-FND-001]), ERP permission + BFF wiring ([ERP-FND-002]), billing gating (SKY-32..36 - enforced externally, does not block building).

This document is the complete, unambiguous specification for building the Finance & Accounting module. Follow sections in order; every task in the build checklist (§12) links back to the section that defines it.

**Depends on:** shared `services/core` skeleton + identity permission PR ([ERP-FND-001], [ERP-FND-002]).
**Team contract:** aligned with the Sales & CRM spec (Swalih) and the Inventory spec (Abhinav); cross-module money flows go through **ports** (§2.7), never direct table access.

---

## 1. Overview

### 1.1 What this module is

Finance is the **system of record for money**. Other modules *promise* things (an order promises a sale; a delivery promises stock movement). Finance records the *truth*: every dollar of revenue, expense, asset, and liability - under double-entry bookkeeping, so the books always balance.

Three rules govern everything here:

1. **Double-entry, always.** Every money event is written twice (money leaves one account, enters another). An entry that does not balance is refused.
2. **Accrual basis.** Revenue is recognized when it is *earned* (invoice approved), not when cash arrives. Payment just moves money between assets.
3. **Exact arithmetic.** All money is stored as exact decimal `NUMERIC(18,4)`. Never floating point. `0.1 + 0.2` must be exactly `0.3`.

### 1.2 Module architecture

Finance lives inside the shared ERP service `services/core`, as one feature package beside the other Phase-1 modules. It is a **sibling** - it never reaches into another module's tables.

```
services/core
├── features/crm        (Swalih)
├── features/sales      (Swalih)
├── features/inventory  (Abhinav)
├── features/hr         (Abhikrishna)
├── features/finance    (THIS MODULE - Dennis)
└── features/reporting  (shared)
```

Cross-module money flows go through **ports** (interfaces), never direct table access (see §2.7).

### 1.3 Scope - Phase 1 vs deferred

**In scope (Phase 1):** chart of accounts, double-entry journal entries (draft → posted), fiscal periods with close/lock, invoices (accounts receivable), payments, trial balance, P&L, balance sheet.

**Out of scope (Phase 1, deferred):** accounts payable (vendor bills/payment runs), tax computation (GST/VAT/withholding), fixed assets & depreciation, budgeting, payroll (HR module emits pay-run records to a ledger), treasury/cash management, **multi-currency transactions** (single functional currency; `erp_journal_lines` carries `currency` + `exchange_rate` columns reserved, all = tenant default currency in v1). These are the natural v1.1+ follow-ons and are listed on [FIN-EPIC-001].

---

## 2. Module layout

### 2.1 Folder structure

```
services/core/src/core/
├── api/                  # deps, middleware, v1 router (shared core)
├── core/                 # config, constants, security, permissions (shared)
├── db/                   # base (RLS mixin), session, repository (shared)
├── domain/               # value objects: Money, AccountType, EntryStatus
├── events/               # finance event producers
└── features/
    └── finance/          # ★ THIS MODULE - owns all 7 tables
        ├── models/
        │   ├── chart_of_account.py
        │   ├── journal_entry.py
        │   ├── journal_line.py
        │   ├── invoice.py
        │   ├── invoice_line.py
        │   ├── payment.py
        │   └── fiscal_period.py
        ├── router.py     # HTTP layer - thin
        ├── schemas.py    # request/response shapes
        ├── service.py    # business rules (gates, state machines, numbering)
        ├── ports.py      # what OTHER modules can call
        └── repository.py # the ONLY code touching the database models
```

### 2.2 Core components

| Layer | Job | Plain-English |
|---|---|---|
| Router | Validate HTTP, call service, return JSON | Front desk - takes requests, no real decisions |
| Service | All business rules: balance gates, closed-period gates, state transitions, numbering | Manager - decides what may happen |
| Repository | Read/write rows, atomic status updates | Filing clerk - the only one allowed to touch the cabinet |
| Ports | Declares the invoicing interface other modules call | Contract window - "how to request an invoice" |

Why: business rules are testable without a database; modules can't bypass each other's rules.

### 2.3 Tenant isolation (RLS)

Every table has a `tenant_id` column and a database-level rule:

```
Row is visible/editable only when:  row.tenant_id == the tenant on the current session
```

- Reading another tenant's rows returns **zero rows** (never an error - errors leak existence).
- Writing another tenant's rows is **blocked** by the database.
- All foreign keys between tenant-scoped tables are **composite** - they include `tenant_id`, so a row can never reference another tenant's parent row.

Same mechanism the sales module uses. The database enforces it even if application code has a bug.

### 2.4 Authentication, Authorization, RBAC

- **Authentication:** every request carries the identity JWT (a passport). The core service verifies it (RS256, issuer + audience check) and reads the user and tenant.
- **Tenant check:** the token's tenant must match the routed tenant. A token can never be used against a different business.
- **Authorization (RBAC):** permission checks gate every endpoint.

**Permissions used by this module** (registered in identity in the shared permissions PR - the same one that adds `erp.crm.*` and `erp.sales.*`):

| Key | Role holders | Unlocks |
|---|---|---|
| `erp.finance.read` | org_admin, dept_manager, standard_user, auditor | View entries, invoices, trial balance, reports |
| `erp.finance.write` | org_admin, dept_manager, standard_user | Create drafts, invoices, payments |
| `erp.finance.approve` | org_admin | **Post** entries, **approve** invoices, close periods (the money moments) |

> **Note:** [ERP-FND-002] registers `erp.finance.{read,write}` in the Phase-1 identity migration. `erp.finance.approve` must be added (small FND-002 follow-up or the finance migration) before the approve endpoints can grant it. Open point: confirm `auditor` read grant matches the role-seed convention in FND-002.

> **Open point (raise with team):** the Sales doc (2.4) says permissions come from the JWT. Identity actually checks the **database per request**. Recommended: DB-backed (matches identity + inventory, no token staleness). Team decision needed.

### 2.5 Events

Finance announces what it did - but only **after** the database commit succeeds. A failed transaction never emits an event.

| Event | When it fires | Meaning |
|---|---|---|
| `finance.journal_entry.posted` | an entry is posted | A balanced entry is now history |
| `finance.invoice.created` | an invoice is issued | A bill exists (e.g. from a sales order) |
| `finance.invoice.approved` | an invoice is approved | Revenue is now recognized |
| `finance.payment.applied` | a payment is applied | Cash came in; AR went down |

Dev: `KAFKA_BROKERS` unset → producers just log (no-op). Later: real Kafka.

### 2.6 Errors, pagination, idempotency

- **Errors:** RFC 7807 envelopes - code, message, details, request_id.
- **Pagination:** repo's existing offset/limit `ListResponse` convention (matches identity). *(Sales doc proposes cursor-based - flag for a team decision.)*
- **Idempotency - the "never record money twice" rule.** Three layers:
  1. Every automatically-created entry is stamped with **where it came from** (e.g. `source='invoice'` + invoice id). The database refuses to create two entries with the same stamp.
  2. State transitions only succeed if the row is still in the expected state (e.g. only a *draft* can be *issued*). Replays find the state already changed and return the existing result.
  3. Re-requesting an invoice for the same order returns the **existing** invoice.

### 2.7 Cross-module communication

```
[features/sales]  order fulfilled
        |  calls the Invoicing port (implemented by finance)
        v
[features/finance]  creates invoice (issued) + lines + numbering, returns invoice id
        |  (revenue is NOT touched here - that happens at approval)
        v
[features/sales]  emits sales.order.fulfilled {order_id, invoice_id}
```

> **Open point (with Swalih):** the port currently passes only `(tenant_id, order_id)`, which forces finance to read sales' tables. Recommend a shared `SalesOrderForInvoicing` DTO (order id, customer id, lines, amounts, terms) so finance never touches sales tables.

### 2.8 API schemas - request/response examples

#### create_chart_of_account

`POST /api/v1/finance/chart-of-accounts` - `erp.finance.write`

```json
# request
{
  "code": "1100",
  "name": "Accounts Receivable",
  "account_type": "asset"
}

# response - 201
{
  "id": "9f6c...",
  "code": "1100",
  "name": "Accounts Receivable",
  "account_type": "asset",
  "is_active": true,
  "created_at": "2026-08-11T09:00:00Z"
}
```

Validation: `account_type` in {asset, liability, equity, revenue, expense}; `code` unique per tenant - else 409.

#### create_journal_entry

`POST /api/v1/finance/journal-entries` - `erp.finance.write`

```json
# request
{
  "entry_date": "2026-08-11",
  "memo": "Monthly rent",
  "lines": [
    { "account_code": "6100", "debit": "5000.00", "credit": null },
    { "account_code": "2110", "debit": null, "credit": "5000.00" }
  ]
}

# response - 201
{
  "id": "7a12...",
  "entry_date": "2026-08-11",
  "memo": "Monthly rent",
  "status": "draft",
  "lines": [
    { "account_code": "6100", "debit": "5000.00", "credit": null },
    { "account_code": "2110", "debit": null, "credit": "5000.00" }
  ],
  "created_at": "2026-08-11T09:05:00Z"
}
```

Validation: every `account_code` exists + is active in the tenant's COA (else 404); each line **debit XOR credit** (exactly one set, non-zero); sum(debit) == sum(credit) (else 422). Entries are created as `draft` - nothing real yet. *(Rent is accrued to Accounts Payable - expense recognized now, paid later.)*

#### post_journal_entry

`POST /api/v1/finance/journal-entries/{id}/post` - `erp.finance.approve`

```json
# response - 200
{
  "id": "7a12...",
  "status": "posted",
  "posted_at": "2026-08-11T09:10:00Z",
  "posted_by_user_id": "u_4f2a..."
}
```

Errors: 422 unbalanced, 409 entry_date in a closed period, 409 not draft. Already posted → **200 with existing result** (idempotent - never a 409 for a replay).

#### void_journal_entry

`POST /api/v1/finance/journal-entries/{id}/void` - `erp.finance.write`

```json
# response - 200
{ "id": "7a12...", "status": "voided", "voided_at": "2026-08-11T09:12:00Z" }
```

Rule: `draft` → `voided` only in v1. **Posted history is never deleted or reversed in v1** - v1.1 adds reversal entries. Voiding a posted entry → 409.

#### get_journal_entry

`GET /api/v1/finance/journal-entries/{id}` - `erp.finance.read`

```json
# response - 200
{
  "id": "7a12...",
  "entry_date": "2026-08-11",
  "memo": "Monthly rent",
  "status": "posted",
  "source": "manual",
  "source_ref": null,
  "posted_at": "2026-08-11T09:10:00Z",
  "lines": [
    { "account_code": "6100", "account_name": "Rent Expense", "debit": "5000.00", "credit": null },
    { "account_code": "2110", "account_name": "Accounts Payable", "debit": null, "credit": "5000.00" }
  ]
}
```

#### list_journal_entries

`GET /api/v1/finance/journal-entries?status=posted&from=2026-08-01&to=2026-08-31&limit=50&offset=0` - `erp.finance.read`

```json
# response - 200
{
  "items": [
    { "id": "7a12...", "entry_date": "2026-08-11", "memo": "Monthly rent",
      "status": "posted", "source": "manual",
      "debit_total": "5000.00", "credit_total": "5000.00" }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

#### deactivate_chart_of_account

`POST /api/v1/finance/chart-of-accounts/{id}/deactivate` - `erp.finance.write`

```json
# response - 200
{ "id": "9f6c...", "code": "1100", "is_active": false }
```

Rule: **never hard-delete** accounts referenced by history; deactivate only. Deleting a referenced account → 409.

#### get_trial_balance

`GET /api/v1/finance/trial-balance?as_of=2026-08-31` - `erp.finance.read`

```json
# response - 200
{
  "as_of": "2026-08-31",
  "accounts": [
    { "code": "1100", "name": "Accounts Receivable", "type": "asset",
      "debit": "1250.00", "credit": "0.00" },
    { "code": "2110", "name": "Accounts Payable", "type": "liability",
      "debit": "0.00", "credit": "5000.00" },
    { "code": "4000", "name": "Revenue", "type": "revenue",
      "debit": "0.00", "credit": "1250.00" },
    { "code": "6100", "name": "Rent Expense", "type": "expense",
      "debit": "5000.00", "credit": "0.00" }
  ],
  "total_debit": "6250.00",
  "total_credit": "6250.00"
}
```

The ledger proof - DEALER-based; total_debit == total_credit is an invariant. *(Example uses two transactions: 5000 rent accrued to AP, and a 1250 invoice approval; §5.2.)*

#### get_pnl_report

`GET /api/v1/finance/reports/pnl?from=2026-08-01&to=2026-08-31` - `erp.finance.read`

```json
# response - 200
{
  "from": "2026-08-01",
  "to": "2026-08-31",
  "revenue": {
    "total": "1250.00",
    "accounts": [ { "code": "4000", "name": "Revenue", "amount": "1250.00" } ]
  },
  "expenses": {
    "total": "5000.00",
    "accounts": [ { "code": "6100", "name": "Rent Expense", "amount": "5000.00" } ]
  },
  "net_income": "-3750.00"
}
```

#### get_balance_sheet

`GET /api/v1/finance/reports/balance-sheet?as_of=2026-08-31` - `erp.finance.read`

```json
# response - 200
{
  "as_of": "2026-08-31",
  "assets": {
    "total": "1250.00",
    "accounts": [ { "code": "1100", "name": "Accounts Receivable", "amount": "1250.00" } ]
  },
  "liabilities": {
    "total": "5000.00",
    "accounts": [ { "code": "2110", "name": "Accounts Payable", "amount": "5000.00" } ]
  },
  "equity": {
    "total": "-3750.00",
    "accounts": [ { "code": "3200", "name": "Retained Earnings", "amount": "-3750.00" } ]
  }
}
```

Invariant: assets == liabilities + equity (`1250 == 5000 + (-3750)`). Reports are **derived from entries, never stored** - same as-of date as the trial balance above, so the two agree.

#### create_invoice (manual)

`POST /api/v1/finance/invoices` - `erp.finance.write`

```json
# request
{
  "customer_id": "c_9b1e...",
  "invoice_date": "2026-08-11",
  "due_date": "2026-09-10",
  "lines": [
    { "description": "Website design", "account_code": "4000",
      "quantity": 1, "unit_price": "1250.00" }
  ]
}

# response - 201
{
  "id": "invc_3c8d...",
  "invoice_number": "INV-2026-00001",
  "customer_id": "c_9b1e...",
  "invoice_date": "2026-08-11",
  "due_date": "2026-09-10",
  "status": "draft",
  "total": "1250.00",
  "lines": [
    { "description": "Website design", "account_code": "4000",
      "quantity": 1, "unit_price": "1250.00", "amount": "1250.00" }
  ]
}
```

#### issue_invoice

`POST /api/v1/finance/invoices/{id}/issue` - `erp.finance.write`

```json
# response - 200
{
  "id": "invc_3c8d...",
  "invoice_number": "INV-2026-00001",
  "status": "issued",
  "issued_at": "2026-08-11T09:12:00Z"
}
```

Rule: `draft` → `issued`. This is the "bill exists" moment (emits `finance.invoice.created`), **not** the revenue moment. Already issued/approved/paid/voided → 409 (idempotent: replay returns 200 with existing result).

#### approve_invoice

`POST /api/v1/finance/invoices/{id}/approve` - `erp.finance.approve`

```json
# response - 200
{
  "id": "invc_3c8d...",
  "invoice_number": "INV-2026-00001",
  "status": "approved",
  "revenue_entry_id": "7a12...",
  "approved_at": "2026-08-11T09:15:00Z"
}
```

**This is the revenue moment.** Approving runs the posting gate and creates the accrual entry (DR AR / CR Revenue; `source='invoice'`). Invoice must be `issued` - a draft is 409 (issue it first). Already approved/paid/voided → 409 (idempotent replay → 200 with existing result).

#### apply_payment

`POST /api/v1/finance/payments` - `erp.finance.write`

```json
# request
{
  "invoice_id": "invc_3c8d...",
  "amount": "1250.00",
  "method": "card",
  "paid_at": "2026-09-01"
}

# response - 201
{
  "id": "pay_9e2a...",
  "payment_number": "PMT-2026-00001",
  "invoice_id": "invc_3c8d...",
  "amount": "1250.00",
  "method": "card",
  "status": "applied",
  "cash_entry_id": "9d11..."
}
```

Posts DR Cash / CR AR - **never touches revenue**. Amount > outstanding → 422. Invoice must be `approved` → else 409.

#### fiscal periods

`GET/POST /api/v1/finance/fiscal-periods` - read/write; `POST /api/v1/finance/fiscal-periods/{id}/close` - approve

```json
# create request
{ "name": "FY2026-Q1-JAN", "start_date": "2026-01-01", "end_date": "2026-01-31" }

# close response - 200
{ "id": "fp_8b2e...", "name": "FY2026-Q1-JAN", "is_closed": true }
```

Rule: posting a journal entry with `entry_date` inside a **closed** period → 409. Closing is the admin `approve` action; reopening requires logged override (future).

---

## 3. Data model (tables)

All tables: `id UUID`, `tenant_id UUID NOT NULL`, `created_at`, `updated_at`; money `NUMERIC(18,4)`; RLS policy on every table; composite tenant-scoped FKs.

| Table | Columns (key ones) | Rules |
|---|---|---|
| `erp_chart_of_accounts` | `code`, `name`, `account_type`, `is_active` | UNIQUE(tenant_id, code); type in 5 categories |
| `erp_fiscal_periods` | `name`, `start_date`, `end_date`, `is_closed` | UNIQUE(tenant_id, name) |
| `erp_journal_entries` | `entry_date`, `memo`, `status`, `source`, `source_ref`, `posted_at`, `posted_by_user_id` | UNIQUE(tenant_id, source, source_ref) - the idempotency lock |
| `erp_journal_lines` | `entry_id`, `account_id`, `debit`, `credit`, `currency`, `exchange_rate` | composite FK (tenant_id, entry_id), (tenant_id, account_id); CHECK debit XOR credit; no zero lines; `currency` = tenant default in v1 (reserved for multi-currency) |
| `erp_invoices` | `invoice_number`, `customer_id` (UUID ref), `invoice_date`, `due_date`, `status`, `total` | UNIQUE(tenant_id, invoice_number) |
| `erp_invoice_lines` | `line_no`, `description`, `account_id`, `quantity`, `unit_price`, `amount` | composite FK (tenant_id, invoice_id) + (tenant_id, account_id) |
| `erp_payments` | `payment_number`, `invoice_id`, `amount`, `method`, `paid_at`, `status` | composite FK (tenant_id, invoice_id); UNIQUE(tenant_id, source, source_ref) |

Not here: customers (CRM owns), orders (sales owns), floats, hard-deletable history, vendor bills / AP (deferred), tax lines (deferred).

---

## 4. State machines

```
journal_entry:  draft --post--> posted --(v1.1: reversal)--> voided
                  +---------void---------> voided        (pre-post only in v1)

invoice:        draft --issue--> issued --approve--> approved --pay--> paid
                  |                 |
                  +----void---------+----void---------> voided
```

Every transition = conditional update (`WHERE status = <expected>`); rowcount==1 wins, 0 = already done (idempotent → 200 with existing result). Pattern copied from the sales spec (4.3).

- `void` is allowed from `draft` and `issued` only. `posted`/`approved`/`paid`/`voided` are terminal in v1 (reversals arrive in v1.1).
- `approve` requires `issued`. `pay` requires `approved`.

---

## 5. Business flows

### 5.1 Manual entry → post

Draft saved (unbalanced OK) → `post` runs three gates: **balance**, **period open**, **still draft** → committed → event fires. Posting into a closed period → 409.

### 5.2 Sale → Invoice → Revenue → Payment (cross-module)

```
[Sales] order confirmed -> [Sales] fulfil -> InvoicePort.create_from_order
  -> [Finance] erp_invoices(issued) + lines + numbering INV-2026-00001   (no accrual yet)
  -> return invoice_id -> [Sales] sales.order.fulfilled{order_id, invoice_id}
  -> [Finance] approve_invoice -> post accrual entry (DR AR / CR Revenue; source='invoice')
  -> later: [Finance] apply_payment -> DR Cash / CR AR -> invoice paid
```

**Revenue is touched only at approval; payment only moves assets.** `create_from_order` is idempotent - replay returns the existing invoice. This matches rule #2 (accrual) and `approve_invoice` (which returns `revenue_entry_id`).

### 5.3 Void

From `draft`/`issued` only in v1. Posted history is never deleted - v1.1 adds reversal entries (DR Revenue / CR AR, source=`reversal`).

---

## 6. Numbering & reference data

- `INVOICE_PREFIX = "INV"`, `PAYMENT_PREFIX = "PMT"`; format `{prefix}-{year}-{seq:05d}`; constants live in `core/constants.py` beside `SALES_ORDER_PREFIX` (sales spec 3.5). Sequence generated in-transaction, UNIQUE(tenant_id, number).
- `core/seed.py`: finance seeds none (COA is tenant data via API; payment terms live on CRM customers).

---

## 7. API reference (summary)

| Method | Path | Permission |
|---|---|---|
| GET/POST | `/finance/chart-of-accounts` | read / write |
| POST | `/finance/chart-of-accounts/{id}/deactivate` | write |
| GET/POST | `/finance/journal-entries` | read / write |
| POST | `/finance/journal-entries/{id}/post` | approve |
| POST | `/finance/journal-entries/{id}/void` | write |
| GET | `/finance/journal-entries/{id}` | read |
| GET/POST | `/finance/fiscal-periods` | read / write |
| POST | `/finance/fiscal-periods/{id}/close` | approve |
| GET | `/finance/trial-balance?as_of=` | read |
| GET | `/finance/reports/pnl`, `/finance/reports/balance-sheet` | read |
| GET/POST | `/finance/invoices` | read / write |
| POST | `/finance/invoices/{id}/issue` | write |
| POST | `/finance/invoices/{id}/approve` | approve |
| POST | `/finance/invoices/{id}/void` | write |
| POST | `/finance/payments` | write |

All under base `/api/v1`, tenant-isolated, RFC 7807 errors.

---

## 8. Common error codes

| Code | Meaning |
|---|---|
| 401 | Missing/invalid/expired JWT |
| 403 | Tenant mismatch or missing permission |
| 404 | Unknown id / code / other tenant (never leak existence) |
| 409 | Illegal state transition, closed period, duplicate (source, source_ref) / invoice number / COA code, deactivating a referenced account |
| 422 | Unbalanced entry, bad line (both/neither debit & credit, zero amount), amount > outstanding |

Idempotent replays of post/approve/issue/pay return **200 with the existing result**, never a 409.

---

## 9. Backend-for-frontend proxy routing

Frontend calls `/api/*`; the BFF routes the `finance` segment to `services/core:8001`. The `finance` segment is **not yet** in [ERP-FND-002]'s routing (that PR routes `crm|sales|inventory`); adding `finance` to `CORE_SEGMENTS` + sidebar gating on `erp.finance.read` lands with **FIN-UI-003**. Frontend finance API client mirrors `identity-api.ts`; sidebar ERP group shows **Finance** when user holds `erp.finance.read`.

---

## 10. Development environment

- Mirror identity layout inside `services/core`. Alembic: `version_table = alembic_version_core` (identity uses the default `alembic_version` - must not collide). Core migrations: `0001_initial` (RLS base, [ERP-FND-001]), `0002_inventory`, `0003_crm_sales`, **`0004_finance`** (this module: all `erp_*` finance tables + composite FKs + CHECKs + RLS policies).
- Env: DB URL, `KAFKA_BROKERS` (optional), JWT public key, dev port 8001.
- Make targets: `dev-core`, `test-core`, `migrate-core`.

---

## 11. Testing

- **Unit** (`tests/unit/features/test_finance_service.py`): balance gate, zero-line, closed-period, idempotent post/issue/approve, DEALER trial balance, accrual-on-approve (never at issue/payment). Fake repository, no DB.
- **Integration** (`tests/integration/api/test_finance_api.py`): full HTTP flows - create draft → post → create/issue/approve invoice → apply payment.
- **Tenant isolation** (`test_tenant_isolation.py`): two tenants; each sees zero rows of the other; cross-tenant writes blocked by RLS; composite FKs hold.
- **Factories** (`tests/factories/finance_factories.py`) mirroring sales.
- CI: lint → typecheck (mypy) → build (existing pipeline); `lint-imports` guard: features never import another feature's models.

---

## 12. Definition of Done

- [ ] All endpoints per section 7 work against a real DB with RLS
- [ ] A sale → invoice → payment can complete end-to-end via the port (5.2); revenue entry exists only after approval
- [ ] Replay of post/issue/approve/payment/invoice returns the existing result (never duplicates)
- [ ] Unbalanced, zero-line, closed-period, over-payment, issue-a-draft-before-approve all refused
- [ ] Two-tenant isolation test passes
- [ ] Events fire only after commit; no-op producers in dev
- [ ] Lint + typecheck + build + import-lint green
- [ ] Identity permission keys `erp.finance.*` present and mapped to roles (including `erp.finance.approve`)

---

## 13. Open points (to raise with team)

1. **Permissions source** - DB per request (recommended; matches identity) vs JWT claim (sales doc 2.4).
2. **`create_from_order` payload** - propose shared `SalesOrderForInvoicing` DTO so finance never reads sales tables.
3. **Pagination** - offset/limit (existing lib) vs cursor (sales doc 2.6).
4. **Legacy `erp.invoice.*` keys** - replace/alias to `erp.finance.*`?
5. **`erp.finance.approve` registration** - add to [ERP-FND-002] follow-up or the finance identity migration.
6. **Payments-to-order reconciliation** - out of scope v1 (finance invoices only).
7. **Basis decision** - this module is **accrual-always** (matches ERP Handbook Ch.05). Product roadmap (`docs/handbooks/01-product-overview.md`) once suggested cash-basis for initial users with accrual at month 5-6; this doc commits to accrual. Confirm with product.

---

## 14. Build order

**Block A (shared / team):**
1. `services/core` skeleton PR - [ERP-FND-001] (already tracked)
2. Identity permissions PR - [ERP-FND-002] registers `erp.{crm,sales,finance,inventory,hr}.*` (read/write families; finance `approve` lands per open point 5)
3. BFF routing - `finance` segment → core:8001 (landed in FIN-UI-003)

**Block B (Dennis-owned):**

| # | Deliverable | Contains | Verify by |
|---|---|---|---|
| F1 | Domain value objects | Money (Decimal, never float), AccountType (5 types), EntryStatus, InvoiceStatus | unit tests: money math, type rules |
| F2 | Database models + migration 0004 | All 7 `erp_*` tables - composite FKs, CHECKs (debit XOR credit), RLS policies, UNIQUE constraints | `alembic upgrade head`; two-tenant row visibility |
| F3 | Repository + service | atomic state transitions (`WHERE status=...`), posting gates (balance, closed period), numbering INV-/PMT- | unit tests with a fake repository |
| F4 | HTTP layer | schemas.py, router.py, deps wiring (require_permission, tenant context) - COA, journal entries, fiscal periods, trial balance, reports | integration API tests |
| F5 | Cross-module invoicing | create_from_order (idempotent, issued only), issue, approve (accrual entry), apply payment | integration: sales fulfil → invoice → revenue → payment |
| F6 | Events | finance.journal_entry.posted, invoice.created, invoice.approved, payment.applied - after commit, no-op producers in dev | unit: event fires only after commit |
| F7 | Tests + CI + Makefile | unit / integration / two-tenant isolation suites, factories, dev-core / test-core / migrate-core, import-lint guard | full CI green |

**Sequencing note:** F5 is the integration point with Swalih - his "fulfil" flow calls your `create_from_order` (issued only; revenue happens at his later `approve` or the finance API). Coordinate so his fulfil and your invoicing land together or behind the agreed contract.

---

## 15. What you need to decide before starting

1. Permissions source (DB per request vs JWT claim) - recommend **DB**, matches identity.
2. `create_from_order` payload - recommend the shared DTO so you never read sales tables.
3. Pagination - offset/limit (matches existing libs) vs cursor (sales doc).
4. Legacy `erp.invoice.*` keys - replace/alias to `erp.finance.*`.
5. `erp.finance.approve` registration timing (open point 5).
