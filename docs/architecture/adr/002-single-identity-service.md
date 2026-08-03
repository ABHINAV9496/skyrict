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
├── db/           # async engine/session + generic repository
├── models/       # SQLAlchemy ORM models
├── domain/       # value objects
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

Split into real microservices **only if** we hit a concrete scaling reason (e.g., audit logging throughput exceeds identity service capacity).

## Architecture enforcement

The boundaries are enforced in CI with import-linter (root `pyproject.toml`):

- **Feature independence**: the nine `identity.features.*` packages never import one another, even indirectly. The `api/deps.py` composition root is the sole cross-feature wiring point, and the mfa/passkeys/sso features respond with explicit 501s until implemented.
- **Foundations**: `core`, `db`, `models`, `domain`, `events` never depend on `features` or `api`.

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
- Each service layer has its own repository — DB access is already isolated
- Event emission from each service layer means we can split on event consumers later
