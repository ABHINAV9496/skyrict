# Skyrict Finance & Accounting Module

**Owner:** Dennis
**Depends on:** shared `services/core` skeleton + identity permission PR
**Team contract:** Aligned with the Sales & CRM spec (Swalih) and the Inventory spec (Abinav)

---

## 1. Overview

### 1.1 What this module is

Finance is the **system of record for money**. Other modules *promise* things (an order promises a sale; a delivery promises stock movement). Finance records the *truth*: every dollar of revenue, expense, asset, and liability - under double-entry bookkeeping, so the books always balance.

Three rules govern everything here:

1. **Double-entry, always.** Every money event is written twice (money leaves one account, enters another). An entry that does not balance is refused.
2. **Accrual basis.** Revenue is recognized when it is *earned* (invoice approved), not when cash arrives. Payment just moves money between assets.
3. **Exact arithmetic.** All money is stored as exact decimal (18,4). Never floating point. 0.1 + 0.2 must be exactly 0.3.

### 1.2 Module architecture

Finance lives inside the shared ERP service `services/core`, as one feature package beside the other Phase-1 modules. It is a **sibling** - it never reaches into another module's tables.

```
services/core
├── features/crm        (Swalih)
├── features/sales      (Swalih)
├── features/inventory  (Abinav)
├── features/hr         (Abhikrishna)
├── features/finance    (THIS MODULE - Dennis)
└── features/reporting  (shared)
```

Cross-module money flows go through **ports** (interfaces), never direct table access (see 2.7).

---

## 2. Module layout

### 2.1 Folder structure

```
src/core/
├── api/                  # deps, middleware, v1 router (shared core)
├── core/                 # config, constants, security, permissions (shared)
├── db/                   # base (RLS mixin), session, repository (shared)
├── domain/               # value objects: Money, AccountType, EntryStatus
├── models/               # ALL tables, one file each, Erp* names
│   ├── erp_chart_of_account.py
│   ├── erp_journal_entry.py
│   ├── erp_journal_line.py
│   ├── erp_invoice.py
│   ├── erp_invoice_line.py
│   ├── erp_payment.py
│   └── erp_fiscal_period.py
├── events/               # finance event producers
└── features/
    └── finance/
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
| `erp.finance.approve` | org_admin | **Post** entries, **approve** invoices (the money moments) |

> **Open point (raise with team):** the Sales doc (2.4) says permissions come from the JWT. Identity actually checks the **database per request**. Recommended: DB-backed (matches identity + inventory, no token staleness). Team decision needed.

### 2.5 Events

Finance announces what it did - but only **after** the database commit succeeds. A failed transaction never emits an event.

| Event | When it fires | Meaning |
|---|---|---|
| `finance.journal_entry.posted` | an entry is posted | A balanced entry is now history |
| `finance.invoice.created` | an invoice is issued | A bill exists (e.g. from a sales order) |
| `finance.invoice.approved` | an invoice is approved | Revenue is now recognized |
| `finance.payment.applied` | a payment is applied | Cash came in; AR went down |

Dev: `KAFKA_BROKERS` unset -> producers just log (no-op). Later: real Kafka.

### 2.6 Errors, pagination, idempotency

- **Errors:** RFC 7807 envelopes - code, message, details, request_id.
- **Pagination:** repo's existing offset/limit `ListResponse` convention (matches identity). *(Sales doc proposes cursor-based - flag for a team decision.)*
- **Idempotency - the "never record money twice" rule.** Three layers:
  1. Every automatically-created entry is stamped with **where it came from** (e.g. `invoice` + invoice id). The database refuses to create two entries with the same stamp.
  2. State transitions only succeed if the row is still in the expected state (e.g. only a *draft* can be *posted*). Replays find the state already changed and return the existing result.
  3. Re-requesting an invoice for the same order returns the **existing** invoice.

### 2.7 Cross-module communication

```
[features/sales]  order fulfilled
        |  calls the Invoicing port (implemented by finance)
        v
[features/finance]  creates invoice + posts accrual entry
        |  returns invoice id
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
    { "account_code": "1100", "debit": null, "credit": "5000.00" }
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
    { "account_code": "1100", "debit": null, "credit": "5000.00" }
  ],
  "created_at": "2026-08-11T09:05:00Z"
}
```

Validation: every `account_code` exists + is active in the tenant's COA (else 404); each line **debit XOR credit** (exactly one set, non-zero); sum(debit) == sum(credit) (else 422). Entries are created as `draft` - nothing real yet.

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

Errors: 422 unbalanced, 409 entry_date in a closed period, 409 already posted (idempotent - return existing).

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
    { "account_code": "1100", "account_name": "Accounts Receivable", "debit": null, "credit": "5000.00" }
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

Rule: **never hard-delete** accounts referenced by history; deactivate only. Deleting a referenced account -> 409.

#### get_trial_balance

`GET /api/v1/finance/trial-balance?as_of=2026-08-31` - `erp.finance.read`

```json
# response - 200
{
  "as_of": "2026-08-31",
  "accounts": [
    { "code": "1100", "name": "Accounts Receivable", "type": "asset",
      "debit": "1250.00", "credit": "0.00" },
    { "code": "4000", "name": "Revenue", "type": "revenue",
      "debit": "0.00", "credit": "1250.00" }
  ],
  "total_debit": "1250.00",
  "total_credit": "1250.00"
}
```

The ledger proof - DEALER-based; total_debit == total_credit is an invariant.

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
    "total": "0.00",
    "accounts": [ { "code": "1100", "name": "Accounts Receivable", "amount": "0.00" } ]
  },
  "liabilities": { "total": "0.00", "accounts": [] },
  "equity": { "total": "0.00", "accounts": [] }
}
```

Invariant: assets == liabilities + equity. Reports are **derived from entries, never stored**.

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

**This is the revenue moment.** Approving runs the posting gate and creates the accrual entry (DR AR / CR Revenue). 409 if already approved/paid/voided.

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

Posts DR Cash / CR AR - **never touches revenue**. Amount > outstanding -> 422. Invoice must be `approved` -> else 409.

---

## 3. Data model (tables)

All tables: `id UUID`, `tenant_id UUID NOT NULL`, `created_at`, `updated_at`; money `NUMERIC(18,4)`; RLS policy on every table; composite tenant-scoped FKs.

| Table | Columns (key ones) | Rules |
|---|---|---|
| `erp_chart_of_accounts` | `code`, `name`, `account_type`, `is_active` | UNIQUE(tenant_id, code); type in 5 categories |
| `erp_fiscal_periods` | `name`, `start_date`, `end_date`, `is_closed` | UNIQUE(tenant_id, name) |
| `erp_journal_entries` | `entry_date`, `memo`, `status`, `source`, `source_ref`, `posted_at`, `posted_by_user_id` | UNIQUE(tenant_id, source, source_ref) - the idempotency lock |
| `erp_journal_lines` | `entry_id`, `account_id`, `debit`, `credit` | composite FK (tenant_id, entry_id), (tenant_id, account_id); CHECK debit XOR credit; no zero lines |
| `erp_invoices` | `invoice_number`, `customer_id` (UUID ref), `invoice_date`, `due_date`, `status`, `total` | UNIQUE(tenant_id, invoice_number) |
| `erp_invoice_lines` | `line_no`, `description`, `account_id`, `quantity`, `unit_price`, `amount` | composite FK (tenant_id, invoice_id) + (tenant_id, account_id) |
| `erp_payments` | `payment_number`, `invoice_id`, `amount`, `method`, `paid_at`, `status` | composite FK (tenant_id, invoice_id); UNIQUE(tenant_id, source, source_ref) |

Not here: customers (CRM owns), orders (sales owns), floats, hard-deletable history.

---

## 4. State machines

```
journal_entry:  draft --post--> posted --(v1.1: reversal)--> voided
                  +---------void---------> voided        (pre-post only in v1)

invoice:        draft --issue--> issued --approve--> approved --pay--> paid
                  |                 |
                  +----void---------+----void---------> voided
```

Every transition = conditional update (`WHERE status = <expected>`); rowcount==1 wins, 0 = already done (idempotent). Pattern copied from the sales spec (4.3).

---

## 5. Business flows

### 5.1 Manual entry -> post

Draft saved (unbalanced OK) -> `post` runs three gates: **balance**, **period open**, **still draft** -> committed -> event fires. Posting into a closed period -> 409.

### 5.2 Sale -> Invoice -> Revenue -> Payment (cross-module)

```
[Sales] order confirmed -> [Sales] fulfil -> InvoicePort.create_from_order
  -> [Finance] erp_invoices(issued) + lines + numbering INV-2026-00001
  -> [Finance] post accrual entry (DR AR / CR Revenue; source='invoice')
  -> return invoice_id -> [Sales] sales.order.fulfilled{order_id, invoice_id}
  -> later: [Finance] apply_payment -> DR Cash / CR AR -> invoice paid
```

Revenue is touched **only** at approval; payment only moves assets. `create_from_order` is idempotent - replay returns the existing invoice.

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
| GET | `/finance/journal-entries/{id}` | read |
| GET | `/finance/trial-balance?as_of=` | read |
| GET | `/finance/reports/pnl`, `/finance/reports/balance-sheet` | read |
| GET/POST | `/finance/invoices` | read / write |
| POST | `/finance/invoices/{id}/approve` | approve |
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

---

## 9. Backend-for-frontend proxy routing

Frontend calls `/api/*`; BFF routes the `finance` segment to `services/core:8001` (CORE_SEGMENTS already includes `finance`). Frontend finance API client mirrors `identity-api.ts`; sidebar ERP group shows **Finance** when user holds `erp.finance.read`.

---

## 10. Development environment

- Mirror identity layout inside `services/core`. Alembic: `version_table = alembic_version_core` (identity uses the default `alembic_version` - must not collide). Core migration = `0001_initial` (all `erp_*` tables + composite FKs + CHECKs + RLS policies).
- Env: DB URL, `KAFKA_BROKERS` (optional), JWT public key, dev port 8001.
- Make targets: `dev-core`, `test-core`, `migrate-core`.

---

## 11. Testing

- **Unit** (`tests/unit/features/test_finance_service.py`): balance gate, zero-line, closed-period, idempotent post, DEALER trial balance, accrual-on-approve (never at payment). Fake repository, no DB.
- **Integration** (`tests/integration/api/test_finance_api.py`): full HTTP flows - create draft -> post -> approve invoice -> apply payment.
- **Tenant isolation** (`test_tenant_isolation.py`): two tenants; each sees zero rows of the other; cross-tenant writes blocked by RLS; composite FKs hold.
- **Factories** (`tests/factories/finance_factories.py`) mirroring sales.
- CI: lint -> typecheck (mypy) -> build (existing pipeline); `lint-imports` guard: features never import another feature's models.

---

## 12. Definition of Done

- [ ] All endpoints per section 7 work against a real DB with RLS
- [ ] A sale -> invoice -> payment can complete end-to-end via the port (5.2)
- [ ] Replay of post/approve/payment/invoice returns the existing result (never duplicates)
- [ ] Unbalanced, zero-line, closed-period, over-payment all refused
- [ ] Two-tenant isolation test passes
- [ ] Events fire only after commit; no-op producers in dev
- [ ] Lint + typecheck + build + import-lint green
- [ ] Identity permission keys `erp.finance.*` present and mapped to roles

---

## 13. Open points (to raise with team)

1. **Permissions source** - DB per request (recommended; matches identity) vs JWT claim (sales doc 2.4).
2. **`create_from_order` payload** - propose shared `SalesOrderForInvoicing` DTO so finance never reads sales tables.
3. **Pagination** - offset/limit (existing lib) vs cursor (sales doc 2.6).
4. **Legacy `erp.invoice.*` keys** - replace/alias to `erp.finance.*`?
5. **Who files the shared `services/core` skeleton PR first** (you need it before starting).
6. **Payments-to-order reconciliation** - out of scope v1 (finance invoices only).

---

## 14. Build order

**Block A (shared / team):**
1. `services/core` skeleton PR - whoever lands first (identity layout, RLS base, deps, config, `alembic_version_core`)
2. Identity permissions PR - all five families at once: `erp.{crm,sales,finance,inventory,hr}.*` (one migration)
3. BFF routing - `finance` segment -> core:8001 (already present; verify)

**Block B (Dennis-owned):**

| # | Deliverable | Contains | Verify by |
|---|---|---|---|
| F1 | Domain value objects | Money (Decimal, never float), AccountType (5 types), EntryStatus, InvoiceStatus | unit tests: money math, type rules |
| F2 | Database models + migration | All 7 `erp_*` tables - composite FKs, CHECKs (debit XOR credit), RLS policies, UNIQUE constraints | `alembic upgrade head`; two-tenant row visibility |
| F3 | Repository + service | atomic state transitions (`WHERE status=...`), posting gates (balance, closed period), numbering INV-/PMT- | unit tests with a fake repository |
| F4 | HTTP layer | schemas.py, router.py, deps wiring (require_permission, tenant context) - COA, journal entries, trial balance, reports | integration API tests |
| F5 | Cross-module invoicing | create_from_order (idempotent), approve invoice, apply payment | integration: sales fulfil -> invoice -> revenue -> payment |
| F6 | Events | finance.journal_entry.posted, invoice.created, invoice.approved, payment.applied - after commit, no-op producers in dev | unit: event fires only after commit |
| F7 | Tests + CI + Makefile | unit / integration / two-tenant isolation suites, factories, dev-core / test-core / migrate-core, import-lint guard | full CI green |

**Sequencing note:** F5 is the integration point with Swalih - his "fulfil" flow calls your `create_from_order`. Coordinate so his fulfil and your invoicing land together or behind the agreed contract.

---

## 15. What you need to decide before starting

1. Permissions source (DB per request vs JWT claim) - recommend **DB**, matches identity.
2. `create_from_order` payload - recommend the shared DTO so you never read sales tables.
3. Pagination - offset/limit (matches existing libs) vs cursor (sales doc).
4. Legacy `erp.invoice.*` keys - replace/alias to `erp.finance.*`.
5. Who owns the first shared core-skeleton PR.

