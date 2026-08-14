# Incident: ERP migration 0005 edited in place after being applied (`erp_leave_movements.ref_id`)

**Date:** 2026-08-14
**Severity:** P3 (dev-infrastructure; silent schema drift, no data loss)
**Scope:** Infrastructure / migration hygiene — not HR/Payroll feature scope

First entry in `docs/incidents/` (no prior convention existed). Written to persist in
repo history and to be pasted into a GitHub issue verbatim.

---

## Impact

Any persistent PostgreSQL database migrated on **2026-08-13** between commits
`89e617b` and `8bfcc08` has `erp_leave_movements.ref_id` as `uuid` while the
migration chain claims `varchar(64)`. Alembic never repairs it on its own: the
database's version table already reads `0006`/head, so `alembic upgrade head`
is a no-op, and both `alembic heads` and `alembic current` report everything
fine.

Concretely, the leave-accrual path fails on such a database with
`operator does not exist: uuid = character varying` whenever the ledger writes
a string ref like `'2026'` (the annual-accrual leave year). The local dev
volume for this project hit exactly that. CI databases are immune (ephemeral —
always built from current files); persistent local/shared volumes are not.

## Diagnosis

1. `alembic heads` and `alembic current` both report `0006` — no signal.
2. `\d erp_leave_movements` shows `ref_id` as `uuid`; migration 0005 says
   `sa.String(64)`.
3. `alembic check` against a fresh database passes, because the ORM model and
   the migration file agree today. This is **applied-database ↔ migration-file
   drift**, invisible to any fresh-database metadata comparison.

### Mechanism

- `89e617b` (2026-08-13): migration `0005` created with `ref_id = sa.Uuid()`
  and a placeholder `down_revision` explicitly marked `DRAFT PLACEHOLDER`.
- The migration was **applied to a live (persistent) database** during the
  data-layer window while the chain was still unstable.
- `8bfcc08` (2026-08-13): the design decision changed — the annual-accrual ref
  is a leave-year string, not a UUID — and the applied migration was edited
  **in place** (UUID → `String(64)`) alongside the ORM model, instead of adding
  a new revision.
- The version table already read head, so the edit was never replayed. Drift.

### Why the earlier `down_revision` scrutiny missed this

Careful chain bookkeeping guards against branch/multiple-head problems — but it
assumes the version table is a trustworthy proxy for actual schema state. An
in-place edit of an applied migration breaks that assumption entirely, while
every alembic health check still reports green.

## Mitigation / Recovery

Corrective migration `0007_leave_movements_ref_id_string` (in the repo) changes
`erp_leave_movements.ref_id` to `String(64)`:

- on drifted databases (`uuid`) it converts the type (uuid → text);
- on clean databases it is a no-op (same-type ALTER).

It is safe on both. **Remediation action:** run `alembic upgrade head` on any
persistent database that existed on 2026-08-13. Verified against a scratch
database that reproduced the exact drifted state: `uuid` @ `0006` → `0007`
applied → column `varchar`, pre-existing rows preserved, and a `'2026'` string
ref inserts cleanly. The `downgrade` is intentionally a no-op (reversing to
`uuid` would fail on non-UUID string refs).

**Regression guard (added after this incident):**
`services/core/tests/integration/database/test_migration_roundtrip.py` now
exercises the WHOLE chain — identity base → core `upgrade head` → core
`downgrade base` → core `upgrade head` — on a scratch database it creates and
drops, asserting the sentinel schema (including `ref_id` varchar(64)) after
both upgrades and full teardown after the downgrade. This is the first test
to ever run 0006's six-step downgrade (trigger functions, RLS policies,
seeded permissions, sequences) and 0001's policy teardown as part of a longer
chain unwind. 0007's intentional no-op downgrade is exercised by the same
chain: a non-no-op downgrade would have to reverse to `uuid`, and the test
would fail on the round-trip.

## Prevention

The two obvious rules — "never edit an applied migration" and "don't commit
placeholder `down_revision`s" — are the same workflow problem stated twice.
The rule that actually prevents a repeat, stated as something to do up front:

> **Iterate on schema changes against an ephemeral/disposable database during
> active development. Only apply a migration to a persistent (shared or
> long-lived local) volume once the migration is considered final.**

If you are still reworking a migration's schema or `down_revision`, every apply
should target a scratch database that can be dropped and recreated at will. A
persistent volume should only ever see the migration chain in its final,
merged state. This keeps the version table trustworthy, which is the real
invariant every other guard depends on.

Corollary (the classic rule, still true): once a migration has been applied to
any non-disposable database, never edit it — any correction is a new revision.

## Future work (suggestion — not part of this remediation)

A guard that compares a **deployed** database's actual schema against what the
migration chain claims would catch this class of drift (fresh-database
`alembic check` cannot). This is a meaningfully larger ask — tooling that does
not exist yet — and the team should decide explicitly whether to prioritize it.
It is not required for 0007; 0007 is complete and verified on its own.

## References

- Corrective migration: `services/core/alembic/versions/0007_leave_movements_ref_id_string.py`
- Drift origin commits: `89e617b` (created 0005, `uuid`), `8bfcc08` (edited it in place to `String(64)`)
