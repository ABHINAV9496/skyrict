# Skyrict on Azure (SKY-114)

Bicep Infrastructure-as-Code for the Skyrict beta environment (Container
Apps on a Consumption profile + Flexible Postgres + Redis + ACR + Key Vault
+ Log Analytics), designed to run at **$0/month** after the free-trial
month on the Azure free account's 12-month + always-free allotments.

See:

- [Deploy / rollback / destroy runbook](../../docs/runbooks/azure-iac.md)
- [Cost estimate: trial vs $0 steady-state](../../docs/runbooks/azure-cost-estimate.md)
- [ADR-010: Azure hosting decision](../../docs/architecture/adr/0010-azure-hosting.md)

## Layout

```
infra/azure/
├── main.bicep                  root template - composes all modules
├── bicepconfig.json            lint configuration (pinned Bicep CLI v0.47.16)
├── parameters/
│   └── beta.parameters.json    beta defaults (CI validate/what-if baseline)
└── modules/
    ├── environment.bicep       VNet + Log Analytics + Container Apps Environment
    ├── security.bicep          Key Vault (RBAC) + user-assigned identity
    ├── registry.bicep          Azure Container Registry (admin disabled)
    ├── data.bicep              Flexible Postgres + conditional Azure Redis
    ├── apps.bicep              3 Container Apps + db-init + 3 migration jobs
    └── observability.bicep     subscription cost-budget alerts (50/80/90%)
```

## Topology (beta)

| Resource | Name (`prefix=skyrict`, `envName=beta`) | Notes |
| --- | --- | --- |
| VNet | `vnet-skyrict-beta` (10.16.0.0/16) | infra `/23`, postgres `/24`, pe `/24` |
| Container Apps Env | `cae-skyrict-beta` | Consumption, vnet-integrated, scale-to-zero |
| Log Analytics | `log-skyrict-beta` | 30-day retention |
| Key Vault | `kv-skyrict-beta` | RBAC, soft delete + purge protection |
| UAMI | `id-skyrict-beta` | ACR pull + KV secrets |
| ACR | `skyrictbeta.azurecr.io` | Standard SKU, admin disabled |
| Postgres | `pg-skyrict-beta.postgres.database.azure.com` | B1ms, PG16, private |
| Redis (month 1) | `redisskyrictbeta.redis.cache.windows.net` | C0, private endpoint |
| Apps | `app-identity/core/ai-agent-skyrict-beta` | identity+core external, ai-agent internal |
| Jobs | `job-db-init/identity/core/ai-agent-skyrict-beta` | one-shot, run by CD |

## Two-phase rollout

Phases are enforced by the CD workflow (`cd-azure-beta.yml`) because the
apps' Key Vault secret references must exist **before** their revisions are
created:

1. **Phase 1** — `deployWorkloads=false`: environment, security, registry,
   data, budgets. The CD then seeds the KV secrets (JWT keypair, MFA
   encryption key, sync/ingest tokens) and sets `azure.extensions`.
2. **Phase 2** — `deployWorkloads=true` + `imageTag`: the apps and jobs;
   then CD runs `db-init` → identity → core → ai-agent migrations (identity
   first: it owns `tenants` + `current_tenant_id()` which the others
   reference).

## Deploying locally

Requires [Bicep CLI v0.47.16](https://github.com/Azure/bicep/releases/tag/v0.47.16)
(pinned; CI installs it via `Azure/bicep-setup-action`, and local runs use
`.dev/tools/bicep.exe` - e.g. `wget` the release binary there, the path is
gitignored) and an Azure login with subscription-level Contributor
(budgets) plus RG Contributor.

```powershell
# Validate + what-if against the beta parameters
$bicep build infra/azure/main.bicep
az deployment group validate -g skyrict-beta -f infra/azure/main.bicep -p infra/azure/parameters/beta.parameters.json -p postgresPassword="$env:AZURE_POSTGRES_ADMIN_PASSWORD" -p deployWorkloads=false
az deployment group what-if  -g skyrict-beta -f infra/azure/main.bicep -p <same parameters>
az deployment group create   -g skyrict-beta -f infra/azure/main.bicep -p <same parameters>
```

> The repo parameters file carries an **empty** `postgresPassword` for CI
> validation only. A real apply must override it from
> `AZURE_POSTGRES_ADMIN_PASSWORD` (URL-safe alphanumeric, no `@ ? # &`
> characters). The CD does this automatically.

## First phase-2 apply must follow the CD's ordering

KV secrets (`jwt-private-key`, `jwt-public-key`, `mfa-encryption-key`,
`sync-token`, `ingest-token`) must exist before `deployWorkloads=true`.
`scripts/azure/bootstrap-azure.ps1` seeds them; the CD re-seeds/re-rotates
them idempotently (see the runbook).