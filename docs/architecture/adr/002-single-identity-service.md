# ADR-002: Single identity service with internal modules (not six microservices)

## Status

Accepted

## Date

2026-07-27

## Context

The product handbook describes AuthN, AuthZ, Token, User, Session, and Audit as six separate microservices. However, we are a 4-person team in pre-alpha with zero deployed services. Six services means:

- Six deployments to manage
- Six sets of health checks, retries, timeouts
- Six CI/CD pipelines
- Inter-service communication complexity (gRPC/Kafka between auth services)
- Distributed transaction challenges (user creation spans AuthN + Session + Audit)

## Decision

Build **one `identity` service** using a feature-first layout — each domain owns its router, schemas, service, and repository:

```
services/identity/src/identity/
├── api/          # HTTP boundary: app factory, middleware, DI composition root (deps.py)
├── core/         # shared primitives: config, security, exceptions, tenant context
├── db/           # async engine/session + SqlRepository base (entity <-> ORM adapter base)
├── models/       # SQLAlchemy ORM models
├── domain/       # pure entities + value objects (no framework dependencies)
├── events/       # skyrict-events producers/consumers/handlers
└── features/
    ├── auth/           # Authentication + JWT lifecycle
    ├── users/          # User profiles
    ├── organizations/  # Tenants
    ├── sessions/       # Session tracking
    ├── roles/          # RBAC / authorization
    ├── audit/          # Audit logging
    ├── mfa/            # Multi-factor auth (not yet implemented — 501)
    ├── passkeys/       # WebAuthn (not yet implemented — 501)
    └── sso/            # SAML/OIDC (not yet implemented — 501)
```

Each implemented feature is layared `schemas -> service -> ports -> repository`:

- `service.py` owns the business rules and depends only on the repository **port** (`ports.py`, a Protocol) plus domain entities. It never imports ORM models or touches the session/transaction.
- `repository.py` is the only ORM gateway: all SQLAlchemy lives here, and its public methods accept/return domain entities. It subclasses the `SqlRepository` base in `db/`.
- `ports.py` abstracts persistence only (never business rules) so services can be unit-tested against fakes.
- `mfa`/`passkeys`/`sso` are unimplemented stubs; `roles` still uses the legacy `BaseRepository` for seeding system roles (bootstrap exception).

Split into real microservices **only if** we hit a concrete scaling reason (e.g., audit logging throughput exceeds identity service capacity).

## Architecture enforcement

The boundaries are enforced in CI with import-linter (root `pyproject.toml`):

- **Feature independence**: the nine `identity.features.*` packages never import one another, even indirectly. The `api/deps.py` composition root is the sole cross-feature wiring point, and the mfa/passkeys/sso features respond with explicit 501s until implemented.
- **Foundations**: `core`, `db`, `models`, `domain`, `events` never depend on `features` or `api`.
- **Persistence confinement**: no `identity.features` module may import ORM models or the db layer directly except `*repository.py`, which is the ORM gateway. Services, routers, and schemas only see entities through ports.
- **Domain purity**: `domain` never imports `models`, `db`, `features`, or `api`.
- **API hygiene**: no `identity.api` module imports `models` directly (the `deps.py` composition root wires repositories; the db *session* factory is the transaction boundary at `get_db`).

These contracts check direct imports, so the sanctioned `api.deps` composition-root wiring is not misreported as a feature→db coupling.

## Consequences

### Positive

- One deployment, one set of observability, one CI pipeline
- Shared database transactions (user creation is atomic)
- Simpler local development (`make dev` starts one service)
- Faster iteration for a 4-person team

### Negative

- Audit logging cannot scale independently (acceptable at our scale)
- All auth concerns share the same failure domain (mitigated by good error handling)

### Mitigations

- Clear internal module boundaries make future extraction straightforward
- Each feature owns a repository that adapts domain entities to the ORM — DB access is already isolated behind ports, so a future split keeps services database-agnostic
- Services are unit-tested against fake repository ports (no database required)
- Event emission from each service layer means we can split on event consumers later
