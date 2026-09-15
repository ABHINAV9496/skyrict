# Web Formatting Consolidation — Known Technical Debt

## Status

Open technical debt. No code change in this PR; this document records the
divergence and the future consolidation work so the opportunity is not lost.

## Context

The web app exposes three overlapping display-formatting modules plus a
fourth `formatBytes` helper living inside an API client. They grew
independently per feature area, so equivalent helpers (money, dates) exist
in several places with subtly different behavior.

Measured import surface (source files, `apps/web/src`, as of this audit):

| Module | Importers | Exports |
|---|---|---|
| `src/lib/format.ts` | 27 | `formatMoney`, `formatDate`, `formatDateTime`, `formatRate`, `formatListCount` |
| `src/lib/erp/money.ts` | 18 (17 source + 1 test) | `formatMoney`, `formatNumber`, `formatDate`, `formatPercent` |
| `src/lib/finance/format.ts` | 17 | `formatMoney`, `formatDate`, `formatDateTime`, `toMoney`, `sumMoney`, `extractAmountFromText`, `AccountType` + `ACCOUNT_TYPE_LABELS`, `EntryStatus` + `ENTRY_STATUS_LABELS`, `InvoiceStatus` + `INVOICE_STATUS_LABELS` |
| `src/lib/api/documents-api.ts` | 4 files mention `formatBytes` (1 definition + 3 users) | `formatBytes`, plus a local `formatDate` used by documents components |

## Known behavioral differences

The modules are not drop-in equivalents; each `format*` helper has its own
edge-case contract.

### `formatMoney`

- `lib/format.ts` — locale-aware (`Intl.NumberFormat(undefined, ...)`),
  default currency `USD`, returns `"-"` for empty input, coerces the amount
  through `formatter.format(amount as number)` without a `NaN` guard.
- `lib/erp/money.ts` — hard-coded `en-US`, explicit
  `maximumFractionDigits: 2`, accepts a nullable currency, returns `"-"` for
  non-finite input, and falls back to `"<CODE> <value>"` if the currency code
  is invalid to `Intl`.
- `lib/finance/format.ts` — hard-coded `en-US` USD formatter with
  `minimumFractionDigits: 2`, returns `String(value)` (not `"-"`) for
  non-numeric input.

### `formatDate` / `formatDateTime`

- `lib/format.ts` — **date-only strings are UTC-anchored** before formatting
  (`YYYY-MM-DD` parsed as UTC midnight) so the calendar date stays stable
  regardless of viewer timezone. Invalid input returns `"-"`.
- `lib/erp/money.ts` and `lib/finance/format.ts` — parse with `new Date(value)`
  in local time, return the raw value for unparseable input (not `"-"`).
- `lib/api/documents-api.ts` — local-time parse, returns `"-"` for invalid.

### Percent / rate

- `lib/format.ts` `formatRate` — decimal-scale input (`0.05` → `"5%"`),
  `Intl` percent style, max 2 fraction digits.
- `lib/erp/money.ts` `formatPercent` — percentage-scale input (`42.7` → `"43%"`),
  rounds to whole percent.

### Finance-domain responsibilities

`lib/finance/format.ts` is not purely a formatting module: it owns
finance-specific value utilities (`toMoney`, `sumMoney`,
`extractAmountFromText`) and domain label maps (`AccountType`,
`EntryStatus`, `InvoiceStatus`). `AccountType` is imported by
`src/lib/finance/account-classification.ts`. These belong with the finance
feature and must not be lost or blurred into a generic display module.

## Why this is left as debt (and not fixed here)

This is a ~55-call-site frontend refactor with real behavioral differences
(locale, fraction digits, invalid-input contract, timezone handling), not a
dead-code removal. Normalizing behavior silently would change rendered output
across HR, payroll, CRM, sales, and finance pages without snapshot/unit
coverage to lock the intended results. A dedicated frontend PR can establish
one canonical API and migrate call sites deliberately.

## Future consolidation plan

1. Define the canonical display-format module (recommendation: extend
   `src/lib/format.ts`, keeping the UTC-safe `formatDate` contract) and the
   single `formatMoney` contract (recommendation: nullable-currency
   `lib/erp/money.ts` signature with the `en-US` + `en-US` fallback, or a
   shared locale default — decide explicitly).
2. Decide what stays finance-domain in `lib/finance/format.ts`
   (`toMoney`, `sumMoney`, `extractAmountFromText`, status/account label
   maps) versus what becomes generic.
3. Extract `formatBytes` out of `documents-api.ts` into the canonical
   module and update its three users.
4. Migrate one feature area at a time; keep import shims (re-export from the
   canonical module) until all call sites move.
5. Add snapshot/unit tests per area **before** migrating, pinning the
   intended rendered output for edge inputs (empty, NaN, non-numeric string,
   date-only vs date-time, non-USD currency, invalid currency code).

## Verification required for the future PR

- `pnpm --filter @skyrict/web lint` and `pnpm --filter @skyrict/web test`
  (vitest suites for the moved modules, e.g. `lib/erp/money.test.ts`)
- `pnpm --filter @skyrict/web build` to catch type breaks across the ~55
  import sites
- A timezone-shift regression test for `formatDate` on date-only strings
  (assert the same calendar date across at least UTC and UTC-8/UTC+14)