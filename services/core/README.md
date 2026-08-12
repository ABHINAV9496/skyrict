# Core Service

ERP foundations for Skyrict — hosts every Phase-1 ERP module (finance,
inventory, procurement, sales) plus the shared plumbing all of them depend on:
config (`CORE_` env prefix), tenant context + resolver, Row-Level Security
(`current_tenant_id()` + `after_begin` session wiring), the `Money` value
object, shared API dependencies (`get_tenant_context`, `get_current_user`,
`require_permission`), and health/readiness probes.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | Liveness probe |
| GET | `/api/v1/ready` | Readiness probe |
| GET | `/api/v1/me` | Current user (protected — exercises `get_current_user`) |

## Local Development

```bash
# From repo root
make core-dev

# Or directly
uv run --directory services/core core serve --reload
```

## Database

Core shares the `skyrict_identity` Postgres database with the identity service
(no separate DB container). Consequences:

- Core's RLS function uses `CREATE OR REPLACE FUNCTION public.current_tenant_id()`
  so it is idempotent regardless of migration order.
- Core migrates under its own Alembic version table (`alembic_version_core`) so
  the two services never clobber each other's migration bookkeeping.
- Core's base migration references the `tenants` table created by identity's
  `0001_initial_schema`, so identity must be migrated first (`make setup`).

## Multi-Tenancy / RLS

Tenant isolation follows identity's conventions: every tenant-scoped table has
a `tenant_id` column, `after_begin` sets `app.current_tenant_id` via
`set_config(..., true)` (transaction-local), and RLS policies compare
`tenant_id = public.current_tenant_id()`. Child tables reference their parents
with a **composite FK** `(tenant_id, parent_id)` so referential integrity and
RLS agree: a cross-tenant child row is impossible at the constraint level, not
just filtered at query time. New tenant-scoped tables MUST follow this
convention (see `alembic/versions/0001_initial.py`).

## Environment Variables

See `.env.example`. Prefix: `CORE_`

## Running Tests

```bash
uv run pytest services/core/tests/unit/ -v         # unit tests (no DB)
uv run pytest services/core/tests/integration/ -v  # integration (real Postgres)
```
