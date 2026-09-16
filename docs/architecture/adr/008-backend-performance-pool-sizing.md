# ADR-008: Env-driven asyncpg pool sizing with safe defaults

## Status

Accepted

## Date

2026-09-14

## Context

The `core` and `identity` services both create their async SQLAlchemy engines
with **hardcoded** asyncpg pool parameters:

```python
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)
```

There is no `pool_recycle` at all. This is tied to SKY-99 (backend performance
pass): the pool parameters cannot be tuned per environment without a code
change and redeploy.

Two concrete risks motivate env-driven sizing:

1. **Connection exhaustion.** `pool_size + max_overflow = 30` per process. In
   staging/production the identity deployment runs 2-3 replicas, so the
   service alone can hold 60-90 connections. The shared `skyrict_identity`
   Postgres (Azure Database for PostgreSQL flexible server) has a tier-bound
   `max_connections` (roughly 100 for the default flexible-server tiers). If
   the pool size is never reduced for production, the web service can consume
   more connections than the server allows - and SQLAlchemy pool runs out at
   the shared database even while each pod reports a healthy pool.
2. **Stale connections.** Without `pool_recycle`, Azure and managed Postgres
   close idle connections after ~4-8 minutes (`server closed the connection
   unexpectedly` under burst load). `pool_pre_ping` recovers from this but
   adds one round-trip per checkout; recycling the connection proactively
   before it can be dropped is cheaper and avoids the churn.

The platform rule is that all configuration routes through the pydantic
`Settings` object - application code never calls `os.getenv()` directly
(`core/core/config.py`, `identity/core/config.py`). The hardcoded pool values
in `db/session.py` bypass that invariant.

## Decision

1. **Add three env-driven settings to each service**, prefixed like the rest
   of the service's config (`CORE_DB_POOL_SIZE`, `CORE_DB_MAX_OVERFLOW`,
   `CORE_DB_POOL_RECYCLE` and the `IDENTITY_` equivalents):

   - `DB_POOL_SIZE` — steady-state checkout slots per process. Default `20`
     (preserves historical dev/test behaviour).
   - `DB_MAX_OVERFLOW` — burst slots beyond `pool_size`. Default `10`.
   - `DB_POOL_RECYCLE` — seconds a connection is reused before it is closed
     and reopened. Default `1800`.

2. **The engine construction reads these values** so a staging/production
   deploy sizes the pool purely through environment (deployment manifests +
   secrets), with no code change:

   ```python
   engine = create_async_engine(
       settings.DATABASE_URL,
       echo=settings.DEBUG,
       pool_size=settings.DB_POOL_SIZE,
       max_overflow=settings.DB_MAX_OVERFLOW,
       pool_recycle=settings.DB_POOL_RECYCLE,
       pool_pre_ping=True,
   )
   ```

3. **Defaults never regress local dev.** Dev and test environments keep the
   exact historical `20 + 10` shape because the config defaults match the old
   hardcoded values and `.env.example`/compose overrides repeat them.

4. **Sizing rule of thumb for a managed shared Postgres:** pick
   `pool_size` and `max_overflow` so that

   ```text
   (pool_size + max_overflow) * web_replicas < max_connections
   ```

   with headroom for migrations, admin/psql, and monitoring connections.
   For the current Azure tier this means roughly `15 + 5` per replica in
   staging/production (see the k8s overlay manifests). `pool_recycle` is set
   below the provider's idle-drop window (`1800` < the ~4-8 minute Azure
   default).

5. **The ai-agent service is explicitly out of scope** for this ADR: its
   pool (`10 + 5`) is small enough to be safe, and SKY-99 scopes pool work to
   core + identity. It can adopt the same pattern in a follow-up without an
   ADR change.

## Consequences

### Positive

- Staging/production can be tuned to the DB tier via manifests alone; a tier
  change no longer requires a code change + release.
- Eliminates the `pool_size=20` + `max_overflow=10` + no-recycle combination
  that risks exhausting a ~100-connection Azure server at 3 replicas.
- Proactive `pool_recycle` removes most `server closed the connection
  unexpectedly` occurrences; `pool_pre_ping` remains as the safety net.
- Pool parameters are now visible in one place (config) instead of scattered
  across `db/session.py`.

### Negative

- Two new required-consistency triples of env vars per service: anyone tuning
  the DB must update `pool_size`, `max_overflow`, and `recycle` together.
- Sizing is still a static guess at deploy time - it does not adapt to
  changing replica counts at runtime (a future autoscaler would need to
  feed `max_connections / replicas` dynamically).

### Mitigations

- The runbook (`docs/runbooks/staging-deployment.md`) and the config field
  descriptions state the `(pool_size + max_overflow) * replicas` rule so the
  triple is updated consistently.
- `pool_pre_ping` stays on, so even a recycle miss cannot hand out a dead
  connection.

## References

- SKY-99 ticket (backend performance pass)
- `services/core/src/core/core/config.py` / `services/core/src/core/db/session.py`
- `services/identity/src/identity/core/config.py` / `services/identity/src/identity/db/session.py`
- `infra/k8s/overlays/{staging,production}/identity/deployment.yaml`
- `docs/runbooks/staging-deployment.md`