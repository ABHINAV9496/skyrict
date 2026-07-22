<p align="center">
  <img src="https://img.shields.io/badge/Stage-Alpha-red?style=flat-square" alt="Alpha"/>
  <img src="https://img.shields.io/badge/License-Apache%202.0-blue?style=flat-square" alt="License"/>
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/PRs-Welcome-brightgreen?style=flat-square" alt="PRs Welcome"/>
</p>

<br/>

<p align="center">
  <h1 align="center">Skyrict</h1>
  <p align="center">Event-driven business operations platform with integrated market intelligence and autonomous agent execution.</p>
</p>

---

## Overview

Skyrict is an open-source, AI-native platform that merges business operations (ERP) with real-time market intelligence into a single system. Traditional ERP treats your company as an isolated entity processing internal transactions. Skyrict treats your company as a node in a live global market — ingesting external signals, correlating them with internal operations, and letting AI agents act on the synthesis.

```
                    ┌──────────────────────────────────┐
                    │        Event Backbone (Kafka)     │
                    └──────┬───────────────────┬───────┘
                           │                   │
              ┌────────────▼───────┐  ┌────────▼────────────┐
              │  Intelligence Bus  │  │   Operations Bus     │
              │  (external signals)│  │   (internal txns)    │
              └────────────┬───────┘  └────────┬────────────┘
                           │                   │
                    ┌──────▼───────────────────▼───────┐
                    │     Cross-Domain Event Router     │
                    └──────────────┬───────────────────┘
                                   │
                    ┌──────────────▼───────────────────┐
                    │       Agent Execution Layer       │
                    │   (reasoning · planning · action) │
                    └──────────────────────────────────┘
```

Three core subsystems:

1. **Operations Engine** — Multi-tenant ERP covering finance, inventory, procurement, manufacturing, sales, and HR. Event-sourced, CQRS, domain-driven.
2. **Intelligence Engine** — Ingests market signals from 50+ source categories (search trends, social platforms, competitor data, public datasets). Normalizes, deduplicates, scores, and stores as a queryable knowledge graph.
3. **Agent Layer** — LLM-orchestrated agents that consume both signal buses, reason across domains, and execute within guardrails. Not chatbot wrappers — autonomous actors with tool access.

---

## Design Principles

- **Event-native, not event-sourced as an afterthought.** Every state transition emits a domain event. Agents subscribe to event streams, not poll databases.
- **Signal-driven operations.** Inventory reorder points adjust based on external demand signals, not just internal consumption history. Pricing considers competitor movements. Procurement factors in supply-side market data.
- **Agents are first-class citizens.** Every business process exposes machine-readable capabilities. Agents don't scrape UIs — they call structured APIs.
- **Open core.** The operations engine is fully open. Intelligence connectors and agent capabilities are open. Premium features: managed agent orchestration, enterprise SSO, SLA-backed infrastructure.
- **Composable, not monolithic.** Each domain is an independently deployable service. You run what you need.

---

## Architecture

### Domain Decomposition

```
skyrict/
├── services/
│   ├── identity/          # Auth, JWT, OAuth2, RBAC, multi-tenancy
│   ├── finance/           # GL, AP, AR, fixed assets, tax, payroll
│   ├── inventory/         # Stock levels, movements, warehouse, batch/serial
│   ├── procurement/       # PR → PO → GRN → 3-way match → payment
│   ├── sales/             # Leads → quotes → orders → invoicing → revenue
│   ├── manufacturing/     # BOM, routings, work orders, shop floor
│   ├── hr/                # Employees, org structure, benefits, offboarding
│   ├── intelligence/      # Signal collection, NLP, scoring, knowledge graph
│   ├── agents/            # LLM orchestration, tool registry, guardrails
│   └── analytics/         # OLAP queries, materialized views, NL queries
│
├── infrastructure/
│   ├── gateway/           # API gateway, rate limiting, protocol translation
│   ├── events/            # Kafka producers/consumers, schema registry
│   ├── scheduler/         # Temporal workflows, cron, retry logic
│   └── observability/     # Prometheus, Grafana, Jaeger, structured logging
│
├── data/
│   ├── migrations/        # Alembic-managed schema migrations
│   ├── schemas/           # Pydantic models, domain events, API contracts
│   └── seeds/             # Reference data, chart of accounts templates
│
├── web/
│   ├── app/               # Next.js 15, React 19, shadcn/ui
│   └── embedded/          # Embeddable analytics widgets
│
└── ai/
    ├── models/            # Fine-tuned classifiers, forecasting models
    ├── pipelines/         # Training, evaluation, deployment
    └── prompts/           # Versioned prompt templates, agent configs
```

### Data Architecture

| Store | Purpose | Engine |
|-------|---------|--------|
| **PostgreSQL 16** | Operational data, ACID transactions, row-level security | OLTP |
| **ClickHouse** | Columnar analytics, materialized views, sub-second aggregations | OLAP |
| **Redis 7** | Session state, rate limiting, pub/sub, Celery broker | Cache |
| **Elasticsearch 8** | Full-text search, autocomplete, log analytics | Search |
| **Qdrant** | Vector similarity search, RAG retrieval, semantic matching | Vectors |
| **Neo4j** | Knowledge graph, relationship traversal, entity linking | Graph |
| **Kafka 3.x** | Event backbone, CDC, inter-service messaging | Streaming |
| **S3/MinIO** | Raw data archive, model artifacts, report storage | Objects |

### Event-Driven Communication

Every domain service emits structured events to Kafka. No direct database reads between services. All cross-domain data access is event-driven or via query APIs.

```
Topic naming: {domain}.{entity}.{action}

Examples:
  inventory.stock.level_changed
  finance.journal_entry.posted
  procurement.purchase_order.confirmed
  intelligence.trend.detected
  intelligence.demand.score_updated
  agents.procurement.reorder_triggered
```

Services subscribe only to events they need. Schema registry enforces backward compatibility. Events are immutable, append-only, retained for 90 days minimum.

### Agent Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Agent Runtime                         │
│                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │  Perception  │  │  Reasoning   │  │   Action     │    │
│  │             │  │             │  │             │    │
│  │  • Event    │  │  • LLM call │  │  • API call  │    │
│  │    stream   │  │  • Plan     │  │  • DB write  │    │
│  │  • Context  │  │  • Evaluate │  │  • Emit event│    │
│  │    window   │  │  • Reflect  │  │  • Notify    │    │
│  │  • Memory   │  │             │  │  • Block     │    │
│  └─────────────┘  └─────────────┘  └─────────────┘    │
│                         │                               │
│                  ┌──────▼──────┐                        │
│                  │  Guardrails  │                        │
│                  │             │                        │
│                  │  • SoD rules│                        │
│                  │  • Thresholds│                       │
│                  │  • Approval │                        │
│                  │    gates    │                        │
│                  │  • Audit log│                        │
│                  └─────────────┘                        │
└─────────────────────────────────────────────────────────┘
```

Agents operate within **guardrails**:
- Segregation of duties enforcement
- Monetary thresholds requiring human approval
- Complete audit trail for every agent action
- Automatic rollback on policy violation
- Kill switch per agent, per domain

---

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Language | Python 3.12+ | AI/ML ecosystem, async I/O, Pydantic validation |
| Web framework | FastAPI | Async, type-safe, auto-generated OpenAPI spec |
| ORM | SQLAlchemy 2.0 (async) | Battle-tested, Alembic migrations, async support |
| Task queue | Celery + Redis | Distributed workers, scheduled tasks, retry logic |
| Frontend | Next.js 15 / React 19 / TypeScript / shadcn/ui | SSR, accessibility, component library |
| OLTP | PostgreSQL 16 + pgvector | ACID, row-level security, vector search |
| OLAP | ClickHouse | Columnar storage, 10-100x faster aggregations |
| Cache | Redis 7 | Sessions, rate limiting, pub/sub |
| Search | Elasticsearch 8 / Meilisearch | Full-text search, autocomplete |
| Vector DB | Qdrant | Semantic search, filtering, scalability |
| Graph DB | Neo4j + neomodel | Relationship traversal, knowledge graph |
| Event bus | Kafka 3.x / NATS JetStream | Event streaming, CDC, message brokering |
| Workflow | Temporal | Durable execution, retries, compensation |
| AI inference | PyTorch, HuggingFace, LangChain, LlamaIndex | Model serving, RAG, agent orchestration |
| Infrastructure | Docker Compose → Kubernetes | Local dev to production scaling |
| CI/CD | GitHub Actions | Automated testing, linting, deployment |
| Monitoring | Prometheus + Grafana + Jaeger + Loki | Metrics, traces, logs, dashboards |

---

## Prerequisites

- Python 3.12+
- Node.js 20+
- Docker & Docker Compose v2
- PostgreSQL 16+ (or use Docker)
- Kafka 3.x (or use Docker)

## Quick Start

```bash
git clone https://github.com/skyrict/skyrict.git
cd skyrict

# Boot infrastructure
docker compose up -d

# Install and run
pip install -e ".[dev]"
python -m skyrict migrate
python -m skyrict seed
python -m skyrict serve --dev
```

Dashboard: `http://localhost:3000` — API docs: `http://localhost:8000/docs`

### Environment

```bash
cp .env.example .env
```

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://user:pass@localhost:5432/skyrict` |
| `REDIS_URL` | Redis connection | `redis://localhost:6379/0` |
| `KAFKA_BROKERS` | Comma-separated broker list | `localhost:9092` |
| `AI_PROVIDER` | LLM backend | `openai` / `anthropic` / `ollama` |
| `AI_API_KEY` | Provider API key | `sk-...` |
| `ENCRYPTION_KEY` | Fernet key for data at rest | Generated via `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `SECRET_KEY` | JWT signing key | Random 64-character string |

---

## Development

```bash
make setup          # Install deps, create DB, run migrations
make dev            # Start all services in dev mode
make test           # Run full test suite
make test-cov       # Tests with coverage report
make lint           # Ruff linting + type checking
make migrate        # Run pending migrations
make seed           # Load reference data
make benchmark      # Performance benchmarks
```

### Testing

```bash
make test                    # All tests
make test-unit               # Unit only
make test-integration        # Integration (requires Docker)
make test-e2e                # End-to-end (Playwright)
pytest tests/ -k "finance"   # Domain-specific
```

Test coverage target: 80%+ on business logic, 60%+ overall.

---

## API Design

RESTful by default. Events via Kafka. GraphQL for complex queries. gRPC for internal service-to-service.

```
# Operations API
POST   /api/v1/{org}/journal-entries
GET    /api/v1/{org}/accounts?balance=true
POST   /api/v1/{org}/purchase-orders
POST   /api/v1/{org}/sales-orders/{id}/confirm
GET    /api/v1/{org}/reports/balance-sheet?period={p}

# Intelligence API
POST   /api/v1/intelligence/analyze
GET    /api/v1/intelligence/trends?market={m}
GET    /api/v1/intelligence/competitors/{id}
POST   /api/v1/intelligence/score

# Agent API
POST   /api/v1/agents/execute
GET    /api/v1/agents/{id}/status
POST   /api/v1/agents/{id}/approve
GET    /api/v1/agents/audit-log?agent={id}
```

All mutations are idempotent (keyed on `Idempotency-Key` header). All responses include `X-Request-ID` for tracing.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow, code standards, and PR process.

High-signal contributions we're looking for:

- **Intelligence connectors** — New data source collectors with proper rate limiting, deduplication, and schema normalization
- **Domain logic** — Business process implementations with event emission and saga orchestration
- **Agent capabilities** — New tools, reasoning strategies, guardrail implementations
- **Performance** — Query optimization, caching strategies, benchmark improvements
- **Testing** — Integration tests for cross-domain event flows, agent behavior validation

Not looking for: UI polish PRs without backend substance, documentation-only PRs without context, dependency bumps.

See the [Code of Conduct](CODE_OF_CONDUCT.md) for community standards.

---

## Security

To report a vulnerability, see [SECURITY.md](SECURITY.md). Do **not** open a public issue for security reports.

---

## License

Apache License 2.0. See [LICENSE](LICENSE).

---

<p align="center">
  <a href="https://github.com/skyrict/skyrict/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/skyrict/skyrict?style=social"/></a>
  <a href="https://github.com/skyrict/skyrict/network/members"><img alt="Forks" src="https://img.shields.io/github/forks/skyrict/skyrict?style=social"/></a>
  <a href="https://github.com/skyrict/skyrict/issues"><img alt="Issues" src="https://img.shields.io/github/issues/skyrict/skyrict"/></a>
</p>
