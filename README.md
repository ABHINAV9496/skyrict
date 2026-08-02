<p align="center">
  <img src="https://img.shields.io/badge/Stage-Alpha-red?style=flat-square" alt="Alpha"/>
  <img src="https://img.shields.io/badge/License-Apache%202.0-blue?style=flat-square" alt="License"/>
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/PRs-Welcome-brightgreen?style=flat-square" alt="PRs Welcome"/>
  <a href="https://github.com/nkswalih/skyrict/actions/workflows/ci-identity.yml"><img src="https://github.com/nkswalih/skyrict/actions/workflows/ci-identity.yml/badge.svg" alt="CI - Identity Service"/></a>
</p>

<br/>

<p align="center">
  <h1 align="center">Skyrict</h1>
  <p align="center">Event-driven business operations platform with integrated market intelligence and autonomous agent execution.</p>
</p>

---

## Overview

Skyrict is an open-source, AI-native platform that merges business operations (ERP) with real-time market intelligence into a single system. Traditional ERP treats your company as an isolated entity processing internal transactions. Skyrict treats your company as a node in a live global market — ingesting external signals, correlating them with internal operations, and letting AI agents act on the synthesis.

---

## Repository Structure

```
skyrict/
├── apps/                    # Deployable frontend clients
│   ├── web/                 # Next.js 15 / React 19 / TypeScript
│   ├── mobile/              # Mobile app scaffold
│   └── desktop/             # Desktop app scaffold
│
├── packages/                # Shared TypeScript packages
│   ├── api-client/          # Generated from OpenAPI schemas
│   ├── types/               # Shared TS types/interfaces
│   ├── ui/                  # Shared React components
│   └── auth/                # Token storage, refresh logic
│
├── services/                # Deployable Python microservices
│   ├── identity/            # AuthN, AuthZ, MFA, Sessions, Audit
│   └── _template/           # Scaffold copied for every new service, keeps structure consistent
│
├── libs/                    # Shared Python packages
│   ├── skyrict-common/      # Exceptions, logging, pagination, schemas
│   ├── skyrict-events/      # Kafka event schemas, producer/consumer base classes
│   └── skyrict-testing/     # Test fixtures, factories, JWT key generation
│
├── infra/                   # Infrastructure as Code
│   ├── docker/              # Docker Compose for local dev
│   ├── k8s/                 # Kubernetes manifests (base + overlays)
│   └── terraform/           # Cloud infrastructure
│
├── docs/
│   ├── architecture/adr/    # Architecture Decision Records
│   └── handbooks/           # Product & engineering handbooks
│
├── .github/                 # GitHub governance & CI
│   ├── workflows/           # CI/CD workflows
│   ├── CODEOWNERS           # Team-based review routing
│   └── dependabot.yml       # Automated dependency updates
│
├── pyproject.toml           # uv workspace root
├── package.json             # pnpm workspace root
├── turbo.json               # Frontend task pipeline
├── Makefile                 # Single entrypoint for all dev commands
└── ...
```

### Identity Service Layering

```
services/identity/src/identity/
├── api/              # FastAPI routes, dependency injection
├── core/             # Config, security, middleware, tenant context
├── domain/           # Pure Python entities and value objects
├── services/         # Application/use-case layer (business logic)
├── repositories/     # DB access only (no business logic)
├── models/           # SQLAlchemy ORM models
├── schemas/          # Pydantic request/response DTOs
├── events/           # Kafka event producers/consumers
└── db/               # Async engine, session factory, RLS
```

Why this layering: `api → services → repositories → models`. Business logic never touches the DB directly. JWT verification happens in exactly one place (`core/security.py`). Tenant context flows through a ContextVar, not function parameters.

---

## Tech Stack

| Layer | Choice |
|-------|--------|
| Python package manager | **uv** (workspaces, single lockfile) |
| Language | Python 3.12+ / TypeScript 5.7+ |
| Web framework | FastAPI (async, type-safe, OpenAPI) |
| ORM | SQLAlchemy 2.0 (async) + Alembic |
| Frontend | Next.js 15 / React 19 / shadcn/ui |
| Frontend tooling | pnpm + Turborepo |
| OLTP | PostgreSQL 16 + Row-Level Security |
| Cache | Redis 7 |
| Event bus | Kafka 3.x (KRaft mode) — deferred until 3+ services need async events |
| CI/CD | GitHub Actions (path-filtered) |
| Containers | Docker |

---

## Prerequisites

- Python 3.12+
- Node.js 20+
- Docker & Docker Compose v2
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- pnpm (`npm install -g pnpm`)

## Quick Start

```bash
git clone https://github.com/nkswalih/skyrict.git
cd skyrict

# 1. Install all dependencies
make setup

# 2. Configure the local environment
cp services/identity/.env.example .env
uv run python -m skyrict_testing.generate_keys  # JWT RS256 keys -> .dev/keys/ (gitignored)

# 3. Start dev servers (infra + identity service)
make dev

# 4. In another terminal, start the frontend
make dev-web
```

- API docs: `http://localhost:8000/docs`
- Frontend: `http://localhost:3000`
- Multi-tenant dev: the tenant is resolved from the verified JWT `tenant_id` claim, with an `X-Tenant-ID` header fallback for service-to-service calls. See the [identity service README](services/identity/README.md) for details.

### Manual Setup

```bash
# Python deps
uv sync

# Frontend deps
cd apps/web && pnpm install

# Boot infrastructure (Postgres, Redis)
docker compose -f infra/docker/docker-compose.yml up -d
# Kafka is intentionally deferred — see "Roadmap & Scope" below.

# Run migrations
make migrate

# Start identity service
make dev
```

---

## Development

```bash
# Install git hooks (run once after clone)
./scripts/setup-hooks.sh        # Unix/macOS
.\scripts\setup-hooks.ps1       # Windows

# Common tasks
make setup          # Install deps, create DB, run migrations
make dev            # Start identity service in dev mode
make dev-web        # Start Next.js dev server
make dev-all        # Start everything
make test           # Run all tests
make test-unit      # Unit tests only
make test-cov       # Tests with coverage
make lint           # Ruff + mypy
make format         # Auto-format code
make migrate        # Run pending Alembic migrations
make migrate-create MSG="add users table"  # Create new migration
make seed           # Load reference data
make build          # Build Docker image
make check          # Full CI check (lint + test)
make clean          # Remove build artifacts
make help           # Show all available targets
```

### Git Hooks

```bash
./scripts/setup-hooks.sh        # Unix/macOS
.\scripts\setup-hooks.ps1       # Windows
```

Pre-commit hooks: Ruff lint, Ruff format, mypy, YAML/JSON/TOML validation, large file check, direct push block, conventional commit lint.

### Branch Protection

See [docs/setup/branch-protection.md](docs/setup/branch-protection.md) for required GitHub repository settings to enforce PR-only workflow, required reviews, and CI checks.

---

## Architecture

### Target Architecture (Roadmap)

Not all of these exist yet — this is the intended end state. Today only `identity` is in active development.

```
services/
├── identity/          # Auth, JWT, OAuth2, RBAC, multi-tenancy   (in active development)
├── core/              # ERP domain (finance, inventory, procurement)   (planned)
└── intelligence/      # Signal collection, NLP, scoring, knowledge graph   (planned)
```

Future (aspirational — not yet explicitly scoped):

```
services/
├── agents/            # LLM orchestration, tool registry, guardrails
└── analytics/         # OLAP queries, materialized views
```

### Event-Driven Communication

Every domain service emits structured events to Kafka. No direct database reads between services.

```
Topic naming: {domain}.{entity}.{action}

Examples:
  identity.user.created
  identity.auth.login_success
  inventory.stock.level_changed
  finance.journal_entry.posted
```

### Multi-Tenancy

Row-Level Security (RLS) on PostgreSQL. Every query is scoped to the current tenant via `SET app.current_tenant_id`. Tenant context flows through a `ContextVar`, not function parameters.

---

## Roadmap & Scope

Skyrict is deliberately MVP-first: ship a small, secure, well-tested core before expanding scope. The following are intentionally deferred until a concrete need justifies them: SSO (SAML/OIDC), OPA policy engine, HashiCorp Vault, Kafka event bus (once 3+ services need decoupled async events), SCIM provisioning, and adaptive risk scoring.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow, code standards, and PR process.

---

## Security

To report a vulnerability, see [SECURITY.md](SECURITY.md). Do **not** open a public issue for security reports.

---

## License & Trademarks

Apache License 2.0. See [LICENSE](LICENSE).

Skyrict trademarks and usage guidelines: [TRADEMARK.md](TRADEMARK.md).

---

<p align="center">
  <a href="https://github.com/nkswalih/skyrict/stargazers">
    <img alt="Stars" src="https://img.shields.io/github/stars/nkswalih/skyrict?style=social"/>
  </a>
  <a href="https://github.com/nkswalih/skyrict/network/members">
    <img alt="Forks" src="https://img.shields.io/github/forks/nkswalih/skyrict?style=social"/>
  </a>
  <a href="https://github.com/nkswalih/skyrict/issues">
    <img alt="Issues" src="https://img.shields.io/github/issues/nkswalih/skyrict"/>
  </a>
</p>

---

## Contributors

<p align="center">
  <a href="https://github.com/nkswalih">
    <img src="https://github.com/nkswalih.png?size=80" width="80" height="80" alt="nkswalih" title="nkswalih — Owner"/>
  </a>
  <a href="https://github.com/apps/dependabot">
    <img src="https://avatars.githubusercontent.com/u/49699333?v=4" width="80" height="80" alt="dependabot[bot]" title="dependabot[bot] — Automated dependency updates"/>
  </a>
</p>
