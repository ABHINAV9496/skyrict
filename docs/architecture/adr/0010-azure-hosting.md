# ADR-010: Azure Container Apps hosting for the beta environment

## Status

Accepted

## Date

2026-09-21

## Context

Skyrict needs a public beta environment that:

- runs identity, core, and ai-agent API services (Python/FastAPI, async
  SQLAlchemy 2.0, Pydantic v2) plus a shared Flexible Postgres and Redis;
- is **near-zero cost during the free-trial year** (Azure free account:
  12-month popular services + always-free allotments) without sacrificing a
  production-standard security/ops posture;
- can scale to **zero** between requests (bursty demo/approval traffic)
  and back up automatically;
- keeps secrets out of the repo and out of every app/env surface;
- deploys from GitHub Actions with no static credentials.

Existing state: `infra/terraform/` manages AWS Route 53; `infra/k8s/` +
`cd-staging.yml` deploy an identity-only staging environment to Kubernetes;
the web app ships on Vercel. The beta adds full three-service Azure hosting.

Options evaluated:

| Option | Scale-to-zero | Free-tier fit | Ops load |
| --- | --- | --- | --- |
| **Azure Container Apps (Consumption, vnet)** | Native (`minReplicas: 0`) | Consumption quotas + CAE | Low (PaaS) |
| AKS (Kubernetes) | Node pool only (cluster never sleeps) | No | High (cluster ops) |
| App Service (Linux) | No — always-on plan | Small plans free-ish (F1) but no Postgres-in-VNet pair | Medium |
| Azure Functions (container) | Yes | Yes | Good for FaaS not long-lived FastAPI; no CAE features |
| Keep K8s staging + add services | No (always-on cluster) | No | Reuses existing, but contradicts $0 |

Container Apps wins on the three hard requirements: native scale-to-zero,
Consumption free-tier quotas matching three FastAPI services, and
vnet-integrated Postgres/Redis via private endpoints — all written as
declarative Bicep and deployed by OIDC with zero static secrets.

## Decision

Host the Skyrict **beta** on **Azure Container Apps** (Consumption profile,
vnet-integrated, scale-to-zero) defined entirely in Bicep
(`infra/azure/main.bicep` + `modules/`), deployed by
`.github/workflows/cd-azure-beta.yml` via GitHub OIDC federated identity.

Concrete topology (SKY-114):

- One VNet 10.16.0.0/16; separate subnets for the CAE infra subnet, the
  Postgres Flexible Server (delegated), and private endpoints.
- Three Container Apps on one CAE, `minReplicas: 0`, HTTP-concurrency
  scale rule (100 concurrent requests → `maxReplicas: 2`):
  identity (external :8000), core (external :8001), ai-agent
  (**internal-only** :8000).
- One shared PostgreSQL Flexible Server, **PG 16**, B1ms, 32 GB, private
  VNet access, one database `skyrict_identity`; per-service Alembic version
  tables (`alembic_version`, `alembic_version_core`, `alembic_version_ai`)
  run as one-shot Container Apps Jobs in identity → core → ai-agent order.
- Azure Cache for Redis **Standard C0** with a private endpoint during month
  1; a parameterized `deployManagedRedis=false` + `redisUrlOverride` swap to
  Upstash Serverless Redis keeps the steady state at $0 (both endpoints
  speak `redis://` with TLS — no code change).
- ACR (Standard, admin disabled): pull via user-assigned identity (AcrPull),
  push via the OIDC deploy principal (AcrPush, granted by Bicep).
- Key Vault (RBAC, soft delete + purge protection): the only secret store;
  apps use Key Vault references resolved with the UAMI, seeded by CD.
- Log Analytics (30-day retention) for app diagnostics; subscription-scoped
  cost-budget alerts at 50/80/90%.
- Two-phase rollout: `deployWorkloads=false` (infra + KV + data + budgets) →
  seed KV secrets → `deployWorkloads=true` (apps + jobs) → db-init + alembic
  jobs → health smoke. Applying the same parameters twice is asserted to be
  a no-op in CI.

## Consequences

### Positive

- Native scale-to-zero on a fully managed platform; the free-account
  quotas (1.8M vCPU-s/mo CAE, 750 h + 32 GB Postgres, one free ACR/Redis)
  make the steady state $0/month (see `azure-cost-estimate.md`).
- Every resource is versioned Bicep; `bicep validate`/`what-if` gives
  change review before apply; apply-twice-no-op is CI-enforced.
- No static cloud credentials: GitHub OIDC → AAD app → RBAC, plus AcrPull
  via UAMI. No secrets in the repo, Bicep, logs, or app env.
- PostgreSQL is the exact major version used by CI (16), and each service
  keeps an independent migration chain in one cheap server.

### Negative / trade-offs

- New Azure surface vs the existing K8s staging: parallel IaC to maintain
  until staging is consolidated.
- Subscription-scoped cost budgets force the deploy principal to have
  subscription-level Contributor; narrower custom roles are possible but
  not yet implemented.
- `ai-agent` is internal-only, so it has no public FQDN for smoke tests —
  verification uses revision state / replicas (documented in the runbook).
- No custom domains/TLS yet: `BASE_DOMAIN`, JWKS issuer/audience are
  configured and shared, but a public domain + DNS tenant routing is a
  follow-up (JWT issuer/audience are already aligned across services).

### Review / rollback

- Rollback = re-apply a previous commit's template state or re-run CD with
  the previous image SHA (Bicep is declarative + idempotent); Alembic
  downgrades run through the job pattern. Destroy is documented in
  `docs/runbooks/azure-iac.md` §9.

## Alternatives considered (in brief)

- **AKS / existing K8s cluster**: cannot scale the control plane to zero —
  contradicts the $0 requirement; also heavier ops for a three-service beta.
- **App Service**: no scale-to-zero; paired vnet Postgres is awkward.
- **Azure Functions**: less suited to long-lived FastAPI + long-lived
  request handlers; loses CAE-native secret volumes/jobs for migrations.
- **Keep only K8s staging + add the remaining services**: cheapest
  incremental move but keeps an always-on cluster and never reaches $0.