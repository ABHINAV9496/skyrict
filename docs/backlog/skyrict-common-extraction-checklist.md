# skyrict-common Extraction Checklist

## 1. Purpose

Guide future extraction of cross-service infrastructure into
`libs/skyrict-common` so it happens deliberately, with a canonical owner and
a migration path, instead of by accident when a third copy of the same
helper appears.

Goals:

- Identify candidates for extraction into `libs/skyrict-common`
- Reduce repeated cross-service infrastructure
- Avoid premature extraction (single-service helpers stay where they are)

This document is planning/backlog material only. It performs no extraction
and mandates no code change on its own.

## 2. Existing candidates

Already shared today (`libs/skyrict-common/src/skyrict_common/`):

- `exceptions.py` — `SkyrictError` hierarchy and RFC 7807 mapping
- `logging.py` — `configure_logging`, `get_logger` (structured structlog)
- `pagination.py` — `PaginationParams`
- `schemas.py` — `ErrorDetail`/`ErrorResponse`, `ListResponse`, `PaginationMeta`, `ResponseEnvelope`
- `ai_hr_rules.py` — pure HR rule engine (already invoked from `services/ai-agent` / HR docs)

Other genuinely service-independent helpers discovered during the audit
should be evaluated with the qualification criteria below before moving.

## 3. Candidate qualification criteria

A candidate is extractable only when **all** of these hold:

- [ ] No service-specific business semantics (labels, domain rules, tenant logic)
- [ ] No dependency on service-specific configuration (env vars, settings objects, secrets)
- [ ] Stable API/behavior — not still changing shape
- [ ] Usable by multiple services today (or clearly will be within one milestone)
- [ ] Clear ownership (named owner/team for maintenance)
- [ ] Tests can live with the shared library (no service-only fixtures)

## 4. ADR requirements

Before extraction, an ADR must cover:

- Why extraction is needed (duplication evidence, count of copies)
- Canonical owner of the shared module
- Public API shape (names, signatures, error contract)
- Dependency implications (what the shared lib may and may not import)
- Compatibility/migration strategy (shim/re-export while consumers migrate)
- Versioning policy for the shared lib
- Rollback strategy if a consumer cannot migrate

## 5. Migration procedure

1. Introduce the shared implementation in `libs/skyrict-common`
2. Add a compatibility layer (re-export/shim) where appropriate so current
   import sites keep working
3. Migrate one service at a time (never all at once)
4. Remove the duplicated implementation only after its consumers have
   migrated and passed their gates
5. Update tests for the moved behavior in the shared library
6. Run the affected service's own gate
7. Run the shared library's gate

## 6. Verification gates

- [ ] Unit tests (shared library suite)
- [ ] `ruff check` and `ruff format --check`
- [ ] `mypy` (strict)
- [ ] `bandit`
- [ ] Affected service test suites
- [ ] Import/dependency validation (no service imports leaking into the lib)
- [ ] Docker/boot verification where applicable (service starts with the moved module)

## 7. Explicit non-goals

- No code extraction in this document (D3 is documentation only)
- No invented container/k8s manifests
- No speculative shared abstractions
- No unrelated refactoring folded into an extraction PR

## 8. Known candidates from this audit

- **Core HTTP transport consolidation** is already handled on this branch by
  D1 (`ai_agent/core/core_http.py`). It should **not** be duplicated into
  `libs/skyrict-common` unless a future audit proves it is genuinely
  cross-service (it currently serves only `services/ai-agent`).
- **Frontend formatting consolidation** is D2 technical debt
  (`docs/backlog/web-format-consolidation-debt.md`) and is **web-specific**;
  it is not a `skyrict-common` candidate.
- **Envelope/pagination utilities** already present in `skyrict-common`
  should be evaluated for broader adoption (switching remaining inline
  response shapes onto `ListResponse`/`ResponseEnvelope`) rather than
  duplicated per-service.