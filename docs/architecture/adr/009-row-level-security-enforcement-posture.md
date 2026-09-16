# ADR-009: Row-Level Security enforcement posture

## Status

Accepted

## Context

Every tenant-scoped table has `ENABLE ROW LEVEL SECURITY` and a policy
(`tenant_id = public.current_tenant_id()`), established in identity migration
0001 and replicated across all ai-agent migrations. The tenant GUC
(`app.current_tenant_id`) is set via `set_config` in the `after_begin` hook
(`identity/db/session.py`) from `TenantContext` at the start of each request.

RLS works correctly **only when the database connection uses a non-owner role**.
The `owner` role is a Postgres superuser-equivalent: it bypasses RLS policies
even when `ENABLE ROW LEVEL SECURITY` is set. No migration applies
`FORCE ROW LEVEL SECURITY`, which would make RLS apply regardless of role.

The production database connection strings currently use the owner role, so
RLS policies are inert in production. This means cross-tenant isolation
depends entirely on the application layer until the DB role is restricted.

A3 (preceding commits) adds application-level tenant filters to the session
repository and token flows as immediate defense-in-depth. The refresh-token
tenant assertion (A2) and per-tenant job scoping (A1) close the highest-risk
exploit paths.

## Decision

**Do not add `FORCE ROW LEVEL SECURITY` blindly.**

`FORCE RLS` makes policies apply to table owners, which would require
auditing every code path that relies on the owner role for legitimate admin
operations (background jobs, migrations, diagnostic queries). Applying it
without that audit risks silent breakage.

**Recommended production path: restrict the DB connection role.**

Change the Kubernetes secret (or environment variable) used by the three
Python services and the ai-agent scheduled jobs from the owner role to a
dedicated application role that:

1. owns nothing (no table ownership bypass),
2. has `USAGE` on the `public` schema,
3. has `SELECT/INSERT/UPDATE/DELETE` on application tables,
4. has `EXECUTE` on `public.current_tenant_id()`.

The `tenants_readable` permissive policy on the `tenants` table must grant
`SELECT` to this role for tenant enumeration in background jobs. The
`app.set_config` privilege must also be granted (already available via
`pg_catalog.set_config` when the connection sets the GUC via `set_config` in
`after_begin`).

`FORCE ROW LEVEL SECURITY` remains available as a belt-and-suspenders
addition once the restricted role is verified — a separate ADR should cover
whether it is applied.

## Consequences

- RLS enforcement requires no migration, only a Kubernetes secret change.
- A3's application-layer tenant scoping acts as defense-in-depth while the
  owner role remains in use (dev/staging), and remains valuable even after
  the DB role is restricted (defense in depth is not redundant).
- Background jobs (`suggestion_expiry`, `anomaly_autoclose`, `anomaly_scan`,
  `deal_health_sweep`, etc.) that enumerate tenants from `tenants_readable`
  already pin `TenantContext` per-tenant before operating; they will work
  identically with the restricted role because the listing session uses the
  permissive policy and each per-tenant session sets the GUC.
- The owner role can continue to be used for development and local testing
  where `pg_hba.conf` or connection limits prevent production data access.
