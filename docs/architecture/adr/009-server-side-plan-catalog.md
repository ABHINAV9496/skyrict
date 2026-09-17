# ADR-009: Server-side plan catalog and canonical plan_tier values

## Status

Accepted

## Date

2026-09-15

## Context

Self-service registration lets a user pick a plan from the onboarding UI. The
picker is defined in the frontend (`apps/web/src/config/onboarding.ts`), which
carries the plan names, descriptions and prices (Starter $0, Professional
$29/$24 monthly/annual, Business $79/$66, Enterprise custom). Today the chosen
`planId` is written straight into the shared `tenants.plan_tier` column by the
identity registration service.

Two problems follow:

1. **The frontend is the source of truth for billing.** Prices and limits live
   only in React config. The backend cannot answer "what does this plan cost?"
   or enforce plan limits without a second, informally-synced copy.
2. **The DB stores non-canonical tier names.** The onboarding wizard sends
   `planId: "professional"` (migration `0005` renamed the canonical value
   `pro` → `professional` to match the UI), so `tenants.plan_tier` holds
   `'professional'` while migrations `0001`/`0005`'s downgrade and the `pro`
   default elsewhere assume `'pro'`. Every consumer of `plan_tier` has to
   remember this historical quirk.

SKY-33 (BILLING-DATA-001) adds the billing columns
(trial/subscription/Stripe) to `tenants`. While touching the tenant row it is
cheap to fix the tier naming at the same time, but a schema migration alone
cannot fix the *write path* — a registration still writes
`request.plan_id` straight into the column.

## Decision

1. **The backend owns the plan catalog.** A new billing module
   (`identity/features/billing/plans.py`) defines the four plans with prices
   in **USD cents** (int, never float) and typed feature limits
   (`PlanLimitsResponse` in `billing/schemas.py` is the public contract). The
   frontend prices copied into it become display-only; the server is the
   source of truth for billing amounts and limits.

2. **Two-value mapping, one table of truth.** `PLAN_ID_MAP` maps frontend
   `planId` values (`starter`, `professional`, `business`, `enterprise`) to
   DB-canonical `plan_tier` values (`free`, `starter`, `pro`, `business`,
   `enterprise`). `TIER_MAP` is its reverse. The only difference today is
   `professional → pro`; the rest map identically.

   - `resolve_tier(plan_id)` is applied **at write time** to every
     `request.plan_id` before it reaches `Tenant.plan_tier`
     (`auth/service.py`), so `professional` is never persisted.
   - `resolve_plan_id(tier)` is available for read paths (future API/UI),
     and plan catalogs expose both `id` (frontend value) and `tier`
     (canonical value) so exposed payloads never hide the DB value.

3. **Migration `0028` makes the DB agree.** It re-canonicalizes
   `'professional'` rows to `'pro'` and recreates the
   `ck_tenants_plan_tier` CHECK constraint over the canonical five values.
   The downgrade reverses both, restoring the `0005` constraint. The migration
   is a pair with the write-path change: nothing in this ADR renames any
   frontend `planId` (the UI keeps sending `professional`).

4. **Three billing config settings, all optional.** `BILLING_STRIPE_SECRET_KEY`,
   `BILLING_STRIPE_WEBHOOK_SECRET`, `BILLING_CURRENCY` (default `usd`). All
   default empty in dev/test so the catalog and registration keep working
   without Stripe; staging/production secrets come from the secret manager.
   Amounts in the catalog are expressed in cents relative to
   `BILLING_CURRENCY`; changing the currency does not re-price the catalog.

5. **`free` remains the implicit default tier** — the fixed default for new
   tenants pre-subscription, not a purchasable catalog entry.

## Consequences

### Positive

- The plan catalog, prices and limits are now enforceable backend facts; a
  mislabeled or repriced plan is one source to edit.
- `tenants.plan_tier` holds canonical values; the historical
  `professional` special case is gone from the DB and confined to one
  mapping table (still transparent to the frontend, which continues to send
  the same `planId` it always has).
- Integration/e2e fixtures and future read APIs can stop special-casing the
  legacy literal.

### Negative

- Two names for the same plan in flight (frontend `professional`, DB `pro`).
  Any new consumer must go through `resolve_tier`/`resolve_plan_id` instead
  of assuming the literal either side.
- The catalog module and the frontend onboarding copy can drift; the module
  variable with the mirrored prices is a maintenance target until the
  catalog API (BILLING-API-003) makes the frontend a pure consumer.

### Mitigations

- `PLAN_ID_MAP` is the single mapping source; unit tests
  (`test_billing_plans.py`) assert bidirectionality and mirror the known
  prices from `apps/web/src/config/onboarding.ts`, so a change on either
  side is caught.
- The migration test (`test_migration_0029_billing.py`) proves the up/down
  round-trip on a scratch database, including backfill of legacy
  `professional` rows.
- Future catalog responses expose `id` (frontend) and `tier` (canonical)
  together so no caller needs the mapping to display a plan.

## References

- SKY-33 ticket (BILLING-DATA-001)
- `services/identity/src/identity/features/billing/plans.py`,
  `services/identity/src/identity/features/billing/schemas.py`
- `services/identity/alembic/versions/0029_billing.py`
- `services/identity/src/identity/features/auth/service.py` (write-path
  mapping) and `auth/schemas.py` (`plan_id` literal)
- `services/identity/src/identity/models/tenant.py`
- `apps/web/src/config/onboarding.ts` (frontend plan picker, now display-only)