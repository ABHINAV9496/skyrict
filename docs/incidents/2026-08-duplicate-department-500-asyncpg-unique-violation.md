# Incident: duplicate department returned 500 instead of 409 (`_is_unique_violation` missed asyncpg)

**Date:** 2026-08-14
**Severity:** P3 (wrong HTTP status on a client-error path; data-safe, no corruption)
**Scope:** HR feature error mapping (docs/modules/hr-payroll.md §7 error table)

Found while writing the concurrency/atomicity regression tests for the DoD
`concurrent approve → one guard wins` row. The new
`test_duplicate_department_no_event` expected `409 duplicate-record` (the
documented behavior for "Duplicate employee number / department name") and got
`500 internal-error` instead.

---

## Impact

`POST /api/v1/hr/departments` with a name that already exists in the tenant
raised an unhandled `IntegrityError`, surfacing as RFC 7807 `internal-error`
(500) instead of the documented `duplicate-record` (409). The unique-constraint
violation was detected, but not translated to the domain error the service was
clearly trying to raise:

```python
# service.py — create_department
except Exception as exc:  # DB unique (tenant, name) violation surfaces here.
    if _is_unique_violation(exc):
        raise DuplicateRecordError(f"department {name!r} already exists") from exc
    raise
```

## Diagnosis

`_is_unique_violation(exc)` returned `False` for the actual exception, so the
service re-raised the raw `IntegrityError`. Why:

```python
def _is_unique_violation(exc: Exception) -> bool:
    """True for PostgreSQL unique-violation (23505) — mirrors repo error handling."""
    return getattr(exc, "orig", None) is not None and "23505" in str(getattr(exc, "orig", ""))
```

The check scans the DBAPI exception's message text for the string `"23505"`.
That works for **psycopg**, whose messages embed the SQLSTATE code, but the
application's asyncpg driver does **not** include it:

- psycopg: `duplicate key value violates unique constraint "..."\nDETAIL: ...` — message text carries no SQLSTATE either, actually; psycopg exposes it via `e.diag.sqlstate`.
- asyncpg: the message is `duplicate key value violates unique constraint "uq_erp_departments_tenant_name"` — no `23505` anywhere. The code lives on the exception's `.sqlstate` attribute, which the string scan never looks at.

So the unique-violation translation was effectively dead code on asyncpg: every
duplicate department/employee/leave-type create became a 500.

## Mechanism

- SQLAlchemy `session.flush()` raised `sqlalchemy.exc.IntegrityError` with
  `.orig` = `asyncpg.exceptions.UniqueViolationError`.
- `_is_unique_violation` scanned `str(orig)` for `"23505"` → not present →
  `False`.
- The service re-raised; the router only maps `SkyrictError` subclasses; the
  global handler turned it into `500 internal-error`.

The 409 was never reachable because the detection predicate was written against
a driver whose error format the codebase does not use.

## Mitigation / Recovery

Fixed `_is_unique_violation` (service.py) to read the SQLSTATE from
`orig.sqlstate` (asyncpg) before falling back to the message-text scan
(psycopg):

```python
def _is_unique_violation(exc: Exception) -> bool:
    """True for PostgreSQL unique-violation (SQLSTATE 23505).

    asyncpg surfaces the SQLSTATE on ``orig.sqlstate`` but omits it from the
    message text, so a message scan alone misses it (the string only carries
    the constraint name). psycopg embeds the code in the message instead.
    """
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    sqlstate = getattr(orig, "sqlstate", None)
    if sqlstate is not None:
        return sqlstate == "23505"
    return "23505" in str(orig)
```

Verified: duplicate department create now returns `409` with
`type: https://api.skyrict.io/problems/duplicate-record`.

**Regression guard (added after this incident):**
`services/core/tests/integration/api/test_concurrency_atomicity.py`
`TestNoEventOnFailedTransaction::test_duplicate_department_no_event` posts the
same department name twice and asserts the second response is `409
duplicate-record` and that the failed transaction emitted **no** `hr.*` event.
Before the fix this test failed on `500`; it also covers the
"failed transaction → no event" invariant the DoD row demands.

## Prevention

Two rules make this class of bug visible before it ships:

1. **Every documented error-table row needs an integration test.** The 409
   `duplicate-record` row existed only in the docs; nothing exercised it. The
   test suite now does, via the above regression guard.
2. **Driver-specific predicates must assert against the actual driver.** A
   predicate written against psycopg's error format was never valid on
   asyncpg. When a predicate inspects DBAPI errors, verify it against the
   driver the app actually uses (asyncpg), not the one the message format was
   copied from.

## Related finding (confirmed, not a defect)

While building the concurrency tests, `test_concurrent_approve_cross_requests_invariant`
confirmed the **documented** Rule 3 Phase-1 caveat (docs/modules/hr-payroll.md
§4.2): two different requests for the same employee can both pass the
service-side balance check and both commit negative movements, leaving the
materialized balance stale and the ledger negative. This is an accepted Phase-1
risk (tracked for the concurrency-hardening ticket), so the test is marked
`xfail` with a reference to that section — it will XPASS and fail loudly when
the hardening lands.

## References

- Error-table source of truth: `docs/modules/hr-payroll.md` §7 (`duplicate-record`, 409)
- Service predicate: `services/core/src/core/features/hr/service.py` (`_is_unique_violation`)
- Regression test: `services/core/tests/integration/api/test_concurrency_atomicity.py`
- Related caveat: `docs/modules/hr-payroll.md` §4.2 Rule 3
