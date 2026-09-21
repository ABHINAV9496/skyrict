# skyrict-fabric

Fabric ETL carrier — incremental high-water-mark extraction, Bronze upsert, and
row-parity verification (SKY-117).

This library contains the **testable, CI-validated core** of the Fabric Bronze
pipeline. The declarative per-module-group pipeline definitions live in
`fabric/pipelines/*.pipeline.json` at the repo root; the runbook
(`docs/runbooks/fabric-etl.md`) covers provisioning and scheduling that require
Azure/Fabric tenant credentials this repository must not hold.

## Why this split

| Layer | Location | CI coverage |
|---|---|---|
| Carrier logic (watermark, extract, upsert, parity, run metadata) | `libs/skyrict-fabric/` | ruff, mypy, bandit, pytest (auto via `libs/` scan) |
| Declarative pipeline definitions (5 module groups) | `fabric/pipelines/*.pipeline.json` | not linted (JSON, by design) |
| Provisioning + scheduling runbook | `docs/runbooks/fabric-etl.md` | docs only |

## Incremental semantics (high-water mark, watermark-first)

- `Watermark` is a per-(module_group, source_table) record of the last-synced
  monotonic value (`updated_at` timestamptz or bigint sequence).
- The first run of a table has no watermark → **full load** (parity from zero).
- Subsequent runs extract `WHERE (wm > :hwm) OR (wm = :hwm AND pk > :hwpk)`
  — a compound key that is exact and idempotent: re-running the same watermark
  re-fetches only the boundary row, and `ON CONFLICT (pk) DO UPDATE` makes the
  replay a no-op. No duplicates by construction.
- The HWM is advanced **in the same transaction** as the Bronze upsert, so a
  crashed run does not skip rows (HWM only moves forward, never backward).

## Usage

```bash
# Full load for one module group (no watermark yet)
uv run python -m skyrict_fabric ingest crm-sales --mode full

# Incremental (uses/advances the watermark)
uv run python -m skyrict_fabric ingest crm-sales --mode incremental

# Verify source-vs-Bronze parity and write an evidence report
uv run python -m skyrict_fabric verify-parity crm-sales --report-dir docs/evidence

# Inspect the current watermark
uv run python -m skyrict_fabric show-watermark crm-sales
```

Connection string comes from `FABRIC_SOURCE_DSN` (defaults to the compose-stack
Postgres: `postgresql+asyncpg://skyrict:skyrict@localhost:5432/skyrict_identity`).
Bronze tables are written to the same connection by default (dev parity gate);
in Fabric, the Bronze target is the OneLake lakehouse endpoint.
