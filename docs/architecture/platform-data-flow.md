# Platform Data Flow - Services, Tenant Context, Events, and Jobs

## Status

Accepted - reflects the Phase-1 platform as implemented across
`services/identity`, `services/core`, `services/ai-agent`, the web BFF, and the
local dev infrastructure. Updates as new services or production manifests land.

## Goal

Document how data moves through the Skyrict platform so that every service
boundary, tenant-context hop, event topic, and background job is visible in one
place. This is the reference for:

- where each HTTP request path enters and lands (BFF -> identity/core; core -> ai-agent proxy);
- how tenant identity is carried between services and enforced at the data layer;
- which system events are produced today (Phase-1 stub bus) and what the
  `{domain}.{entity}.{action}` topology looks like;
- which background jobs exist per service and how they keep RLS pinned per tenant;
- how logs flow to the observability stack (structlog -> loki/grafana).

## Service Topology

| Service        | Host port (dev) | Container port | Role                                                                  |
| -------------- | --------------- | -------------- | --------------------------------------------------------------------- |
| Web BFF        | `:3000`         | -              | Next.js app; host-based surface routing; server-side API relay        |
| identity       | `:8000`         | `:8000`        | Authn/z (JWT, MFA, sessions, passkeys, SSO), tenants, users, roles    |
| core           | `:8001`         | `:8001`        | ERP monolith: HR, payroll, inventory, finance, CRM, sales, reporting  |
| ai-agent       | `:8002`         | `:8000`        | AI: chat, NL query, anomalies, narrator, RAG, report builder, guardians |
| postgres       | `:5432` / `:5433` | `:5432`        | Shared `skyrict_identity` DB (pgvector/pgvector:pg18)                 |
| redis          | `:6379`         | `:6379`        | Rate limits, caches, job coordination                                 |
| mailpit        | `:1025`/`:8025` | -              | Dev SMTP sink + UI                                                    |
| nginx          | `:80`           | `:80`          | Local `*.localhost` multi-tenant routing; injects `X-Tenant-Slug`     |
| ollama (opt.)  | `:11434`        | `:11434`       | Local embedding provider (ai-agent only, never at boot)               |

Dev orchestration: `infra/docker/docker-compose.yml` +
`infra/docker/docker-compose.dev.yml`. Kafka is intentionally commented out
until 3+ services need decoupled async events.

## HTTP Request Paths

### Browser -> BFF -> service

The browser only talks to the Next.js app. The BFF
(`apps/web/src/lib/server/auth.ts`) relays server-side:

- `apiBase("core")` -> `CORE_PROXY_TARGET` (default `http://localhost:8001`),
  else `API_PROXY_TARGET` (default `http://localhost:8000`).
- `callBackend` / `callBackendStream` / `callBackendRaw` forward
  `X-Tenant-Slug`, `Authorization`, `User-Agent`, `X-Forwarded-For`.

Host header -> tenant slug in dev via nginx (`infra/nginx/dev.conf`); in prod
the slug is derived from the validated `Host` (`*.skyrict.com`), never from a
`TENANT_SLUG` env fallback (see `docs/architecture/auth-production-model.md`).

### identity `/api/v1`

`identity/api/v1/router.py` mounts: auth, user, org, roles, permissions,
invitations, members, avatars, session, mfa, handoffs, passkey, sso, health.
Identity mints RS256 JWTs (shared issuer/audience), owns tenants/users/roles,
and emits provisioning events for core RBAC mirroring (see Events).

### core `/api/v1`

`core/api/v1/router.py` mounts: health, me, hr, payroll, payroll_automation,
portal, finance (+ automation wave3, payment match, revenue forecast),
inventory, notifications, reporting, reports, crm, crm_workspace, sales,
documents, ai, ai_agents, ai_hr, ai_docs, approval_workflow.

Core is stateless with respect to identity: it verifies the identity-issued
JWT (same issuer/audience, key from `JWT_PUBLIC_KEY`) and authorizes from the
`permissions` claim (`core/core/permissions.py`).

### core -> ai-agent proxy (`/api/v1/ai/*`)

The ai-agent is **never exposed directly**; it is reached only through the core
monolith (`core/features/ai/router.py` + `core/features/ai/proxy.py`):

1. Permission gate: `erp.ai.invoke` plus a module key (SKY-68/90 spec 6.3).
2. `forward_to_ai_agent` relays only `Authorization` + `X-Tenant-Slug`; the
   ai-agent re-verifies the JWT against the relayed slug (spec 1.4).
3. SSRF defence: null `Origin` rejected; target fixed from config, not caller input.
4. Transport failures map to 503 `AiServiceUnavailableError`; ai-agent RFC 7807
   problem bodies pass through; SSE streaming is relayed for chat endpoints.
5. Target: `AI_AGENT_URL` (`http://skyrict-ai-agent:8000` in compose),
   timeout `AI_AGENT_TIMEOUT_SECONDS`; client on `app.state.ai_client`.

### ai-agent -> core (gateways)

ai-agent features call back into core over HTTP when they need ERP data. Every
gateway/loader duplicates the same contract: forward `Authorization` +
`X-Tenant-Slug`, parse the `{data, meta}` envelope, page-loop
(`_MAX_CATALOG_PAGES = 20`, `_CATALOG_PAGE_SIZE = 100`), map transport failures
to `AiUnavailableError`. Present in:

- gateways: `features/{crm,documents,finance,hr_copilot,l3,l4,narrator,nl_query,report_builder}/gateway.py`
  (e.g. narrator `CoreGatewayPort`/`HttpCoreGateway` SKY-63, crm
  `CrmGatewayPort`/`HttpCrmGateway` SKY-61);
- loaders: `features/{finance_lines,supplier_risk,inventory_semantic,rag/ingest}/loader.py`;
- document sync: `CORE_DOCUMENT_URL` (+ `CORE_AI_SYNC_TOKEN`) for
  post-commit embedding sync (SKY-70);
- data-plane URLs: `INVENTORY_SERVICE_URL`, `REPORT_SERVICE_URL` (both
  `http://skyrict-core:8001` in compose).

## Multi-Tenancy & Tenant Context

- Tenant model: PostgreSQL RLS. Every `erp_*` table carries `tenant_id`; RLS
  policy `USING (tenant_id = current_setting('app.current_tenant_id')::uuid)`.
- Resolution: `core/core/tenant_resolver.py` (prod subdomain; header fallback)
  + `core/core/tenant_context.py` (request-scoped `ContextVar`; dependency
  `api/deps.py get_tenant_context()` sets `SET app.current_tenant_id` on the
  request session).
- Posture: ADR-009 - no blind `FORCE ROW LEVEL SECURITY`; prod uses a
  non-owner application role (delegated RLS). Missing/mismatched context is a
  403, never a filtered-by-nothing query.
- Tenant slugs are carried across service hops in `X-Tenant-Slug` (BFF and
  core -> ai-agent proxy) and re-validated at the receiver.

## Events (Phase 1: stub bus, no Kafka)

`libs/skyrict-events` defines the base contracts (`BaseEvent`, `BaseProducer`,
`BaseConsumer`), RFC-3339-ish envelope schemas, and the topic convention
`{domain}.{entity}.{action}`. There is **no broker in Phase 1**; both services
ship logging-only producers so the topology is exercised end-to-end:

- core: `core/events/producers/__init__.py` `StubEventProducer` logs the full
  serialized envelope at INFO after the transaction commits; domain producers
  in `finance_events.py`, `inventory/events/producers/*.py`,
  `crm_events.py`, `documents/events/dispatch.py`.
- Topics today:
  - `identity.tenant.provisioned`, `identity.rbac.role_granted`
    (identity `events/producers/tenant_events.py`);
  - core mirrors those two into `core_roles`/`core_user_roles` via
    `core/events/consumers/__init__.py` -> `consumers/rbac.py` (idempotent);
  - `inventory.stock.level_changed`, `inventory.product.upserted/removed`;
  - `documents.document.uploaded/version_added/updated/deleted/tags_confirmed/downloaded`;
  - `crm.lead.created/status_changed`, `crm.opportunity.stage_changed/won/lost`,
    `crm.customer.created`, `crm.contact.created`,
    `crm.activity.created/completed`, ...
- ai-agent: `ai_agent/events/{producers,consumers}/__init__.py` are reserved
  stubs (SKY-57 later commits); the ai-agent writes its own `ai_audit_log`
  table instead.

## Background Jobs

Jobs that touch tenant-scoped data must pin the request-scoped
`TenantContext` per tenant so RLS binds every statement; workers typically
enumerate active tenants from the DB and process one tenant at a time.

- core:
  - `features/approval_workflow/escalation_worker.py` - overdue-step escalation;
  - `features/notifications/worker.py` - notification batching;
  - `features/reporting/retention_worker.py` - snapshot retention;
  - `features/finance/report_cache_sweep.py` + `cli.py report-cache-sweep` -
    aggregate cache purge per tenant.
- ai-agent (`api/lifespan.py` starts background tasks after provider init;
  repository-only jobs in `core/jobs`, orchestrating jobs in `api/scheduled`):
  - suggestion expiry (SKY-68), anomaly auto-close, scheduled anomaly scan,
    CRM follow-up scan, CRM anomaly scan, deal-health sweep, scheduled
    Guardian report, memory compaction (SKY-90);
  - APScheduler crons: daily narrator (SKY-63), weekly L3 compliance digest
    (HR-AI-003), weekly revenue-forecast refresh (SKY-82 A4).

## Logging & Observability

- `skyrict_common.logging` (`configure_logging`/`get_logger`) is used by every
  Python service; entries carry `request_id`/`tenant_id` where available and
  `exc_info=True` renders full tracebacks.
- Log path: structlog JSON -> stdout -> kubelet -> OTel Collector -> Loki ->
  Grafana (`infra/observability/README.md`). Docker compose flakes configure
  this per container; prod uses the same stdout contract.
- Reference: `LOGGING.md` at repo root.

## Deployment / Infra (current state)

- k8s manifests exist **only for identity** (`infra/k8s/overlays/identity`):
  staging + production deployment/service/ingress; staging ingress routes
  `*.staging.skyrict.com` -> identity, wildcard TLS via cert-manager DNS-01
  (ADR-003); Terraform Route 53 wildcard `*.staging.skyrict.com` ->
  identity ingress.
- core and ai-agent do not yet have k8s manifests or a production ingress;
  in dev they are compose-only, reachable on host `:8001`/`:8002`, and
  ai-agent is only ever hit through core's `/api/v1/ai/*` proxy.

## Non-goals (this doc)

- Kafka production wiring and broker-side guarantees (delivery, DLQ) - Phase 2;
- per-service capacity/HA planning;
- UI component data flow inside the Next.js app (state stores, TanStack Query).