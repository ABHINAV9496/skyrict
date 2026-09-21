// =============================================================================
// SKY-114 - Apps + jobs module
//
// Three Container Apps on the shared Consumption-profile environment:
//   identity  external  :8000  (JWT issuance, sessions, MFA, billing)
//   core      external  :8001  (ERP/HR/finance/reporting monolith)
//   ai-agent  internal  :8000  (RAG/agents - only reachable inside the VNet)
//
// One-shot Container Apps Jobs (deploy-time, run in-VNet by CD):
//   db-init   postgres:16-alpine - creates skyrict_identity + pgvector/pg_trgm
//   identity  alembic upgrade head  (FIRST: creates tenants + current_tenant_id)
//   core      alembic upgrade head  (alembic_version_core)
//   ai-agent  alembic upgrade head  (alembic_version_ai)
//
// Secret architecture:
//   * database-url / redis-url are plain ACA secrets computed from secure
//     params (admin password) + listKeys() - no committed secret material.
//   * jwt-* / mfa / sync-token / ingest-token are Key Vault secret
//     references resolved with the user-assigned identity (clientId).
//     The CD seeds those KV secrets BEFORE deploying workloads.
//   * JWT key files are mounted as SECRET VOLUMES because the services read
//     the PEM files at settings-load time (load_rsa_keys, sys.exit on miss).
//
// Everything in this module is guarded by deployWorkloads so the CD can do
// a two-phase rollout: infra+data+KV first, seed KV secrets, then workloads.
// =============================================================================

@description('Resource name prefix. Defaults to "skyrict".')
param prefix string = 'skyrict'

@description('Deployment environment name (beta/staging/production).')
param envName string

@description('Azure region for all resources.')
param location string

@description('Tags merged onto every resource.')
param tags object = {}

@description('Deploy the apps and jobs. False during phase 1 infra+KV+data rollout.')
param deployWorkloads bool = true

@description('Resource ID of the Container Apps Environment.')
param caeId string

@description('ACR login server (e.g. skyrictbeta.azurecr.io).')
param acrLoginServer string

@description('Resource ID of the user-assigned identity used for ACR pull + Key Vault.')
param uamiId string

@description('Client ID of the user-assigned identity (required for KV secret references).')
param uamiClientId string

@description('Key Vault URI used to build secret references (e.g. https://kv-skyrict-beta.vault.azure.net/).')
param kvUri string

@description('Log Analytics workspace ID for app diagnostic settings.')
param logAnalyticsWorkspaceId string

@description('Image tag for all three services (git SHA from CD).')
param imageTag string

@description('Application ENVIRONMENT value - one of the four app enum values, staging for beta.')
@allowed([
  'dev'
  'test'
  'staging'
  'production'
])
param appEnvironment string = 'staging'

@description('PostgreSQL server FQDN from the data module.')
param postgresFqdn string

@description('PostgreSQL administrator login.')
param postgresLogin string

@description('Name of the shared application database.')
param postgresDbName string

@secure()
@description('PostgreSQL administrator password - used only to build the database-url secret.')
param postgresPassword string

@description('Managed Azure Redis is deployed for month 1 (true = build URL from listKeys, false = use redisUrlOverride).')
param deployManagedRedis bool = true

@description('Azure Redis name (when deployManagedRedis).')
param redisName string = ''

@description('Azure Redis resource ID (when deployManagedRedis).')
param redisId string = ''

@secure()
@description('Redis connection URL override (Upstash Serverless Redis after the month-1 swap). Required when deployManagedRedis=false.')
param redisUrlOverride string = ''

@description('Explicit CORS origins for all three services (JSON array string). Never "*".')
param corsOrigins array = []

@description('Trusted proxy CIDRs (VNet prefix) - used for real client IP extraction.')
param trustedProxies array = ['10.16.0.0/16']

@description('BASE_DOMAIN required by every service in staging/production.')
param baseDomain string

@description('JWT issuer claim shared by identity/core/ai-agent.')
param jwksIssuer string

@description('JWT audience claim shared by identity/core/ai-agent.')
param jwksAudience string

@description('Max replicas per app (scale-to-zero from minReplicas 0).')
param maxReplicas int = 2

@description('Per-container CPU (vCPU) - Consumption profile.')
param containerCpu string = '0.25'

@description('Per-container memory - Consumption profile.')
param containerMemory string = '0.5Gi'

@description('Max concurrent HTTP requests per replica before scaling out.')
param concurrentRequests int = 100

@description('DB connection pool size per replica - lowered for the B1ms free tier.')
param dbPoolSize int = 3

@description('DB connection pool max overflow - 0 keeps B1ms headroom.')
param dbMaxOverflow int = 0

var allTags = union(
  {
    environment: envName
    service: prefix
    managedBy: 'bicep'
  },
  tags
)

var resourceName = '${prefix}-${envName}'
var dbUrl = 'postgresql+asyncpg://${postgresLogin}:${postgresPassword}@${postgresFqdn}:5432/${postgresDbName}?ssl=require'
var redisUrl = deployManagedRedis
  ? 'rediss://:${listKeys(redisId, '2023-08-01').primaryKey}@${redisName}.redis.cache.windows.net:6380/0'
  : redisUrlOverride

// ---------------------------------------------------------------------------
// Shared ACA secrets (all apps/jobs declare the same set)
// ---------------------------------------------------------------------------

var sharedSecrets = [
  {
    name: 'database-url'
    value: dbUrl
  }
  {
    name: 'redis-url'
    value: redisUrl
  }
  {
    name: 'jwt-private-key'
    keyVaultUrl: '${kvUri}secrets/jwt-private-key'
    identity: uamiClientId
  }
  {
    name: 'jwt-public-key'
    keyVaultUrl: '${kvUri}secrets/jwt-public-key'
    identity: uamiClientId
  }
  {
    name: 'mfa-encryption-key'
    keyVaultUrl: '${kvUri}secrets/mfa-encryption-key'
    identity: uamiClientId
  }
  {
    name: 'sync-token'
    keyVaultUrl: '${kvUri}secrets/sync-token'
    identity: uamiClientId
  }
  {
    name: 'ingest-token'
    keyVaultUrl: '${kvUri}secrets/ingest-token'
    identity: uamiClientId
  }
]

// ---------------------------------------------------------------------------
// Secret volumes - the services read PEM key files at settings-load time
// ---------------------------------------------------------------------------

var jwtVolumeIdentity = {
  name: 'jwtkeys'
  storageType: 'Secret'
  secrets: [
    {
      secretRef: 'jwt-private-key'
      path: 'jwt-private.pem'
    }
    {
      secretRef: 'jwt-public-key'
      path: 'jwt-public.pem'
    }
  ]
}

var jwtVolumePublic = {
  name: 'jwtkeys'
  storageType: 'Secret'
  secrets: [
    {
      secretRef: 'jwt-public-key'
      path: 'jwt-public.pem'
    }
  ]
}

// ---------------------------------------------------------------------------
// identity - external, :8000
// ---------------------------------------------------------------------------

resource identityApp 'Microsoft.App/containerApps@2026-01-01' = if (deployWorkloads) {
  name: 'app-identity-${resourceName}'
  location: location
  tags: allTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uamiId}': {}
    }
  }
  properties: {
    environmentId: caeId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      registries: [
        {
          server: acrLoginServer
          identity: uamiId
        }
      ]
      maxInactiveRevisions: 5
      secrets: sharedSecrets
    }
    template: {
      containers: [
        {
          image: '${acrLoginServer}/identity:${imageTag}'
          name: 'identity'
          volumeMounts: [
            {
              volumeName: 'jwtkeys'
              mountPath: '/secrets'
            }
          ]
          resources: {
            cpu: json(containerCpu)
            memory: containerMemory
          }
          env: [
            {
              name: 'IDENTITY_ENVIRONMENT'
              value: appEnvironment
            }
            {
              name: 'IDENTITY_DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'IDENTITY_REDIS_URL'
              secretRef: 'redis-url'
            }
            {
              name: 'IDENTITY_JWT_PRIVATE_KEY_PATH'
              value: '/secrets/jwt-private.pem'
            }
            {
              name: 'IDENTITY_JWT_PUBLIC_KEY_PATH'
              value: '/secrets/jwt-public.pem'
            }
            {
              name: 'IDENTITY_MFA_ENCRYPTION_KEY'
              secretRef: 'mfa-encryption-key'
            }
            {
              name: 'IDENTITY_JWKS_ISSUER'
              value: jwksIssuer
            }
            {
              name: 'IDENTITY_JWKS_AUDIENCE'
              value: jwksAudience
            }
            {
              name: 'IDENTITY_CORS_ORIGINS'
              value: string(corsOrigins)
            }
            {
              name: 'IDENTITY_TRUSTED_PROXIES'
              value: string(trustedProxies)
            }
            {
              name: 'IDENTITY_BASE_DOMAIN'
              value: baseDomain
            }
            {
              name: 'IDENTITY_DB_POOL_SIZE'
              value: string(dbPoolSize)
            }
            {
              name: 'IDENTITY_DB_MAX_OVERFLOW'
              value: string(dbMaxOverflow)
            }
          ]
          probes: [
            {
              type: 'Readiness'
              httpGet: {
                path: '/api/v1/health'
                port: 8000
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              failureThreshold: 3
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/api/v1/health'
                port: 8000
              }
              initialDelaySeconds: 20
              periodSeconds: 30
              failureThreshold: 5
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-scale'
            http: {
              metadata: {
                concurrentRequests: string(concurrentRequests)
              }
            }
          }
        ]
      }
      volumes: [jwtVolumeIdentity]
    }
  }
}

// ---------------------------------------------------------------------------
// core - external, :8001
// ---------------------------------------------------------------------------

resource coreApp 'Microsoft.App/containerApps@2026-01-01' = if (deployWorkloads) {
  name: 'app-core-${resourceName}'
  location: location
  tags: allTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uamiId}': {}
    }
  }
  properties: {
    environmentId: caeId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8001
        transport: 'http'
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      registries: [
        {
          server: acrLoginServer
          identity: uamiId
        }
      ]
      maxInactiveRevisions: 5
      secrets: sharedSecrets
    }
    template: {
      containers: [
        {
          image: '${acrLoginServer}/core:${imageTag}'
          name: 'core'
          volumeMounts: [
            {
              volumeName: 'jwtkeys'
              mountPath: '/secrets'
            }
          ]
          resources: {
            cpu: json(containerCpu)
            memory: containerMemory
          }
          env: [
            {
              name: 'CORE_ENVIRONMENT'
              value: appEnvironment
            }
            {
              name: 'CORE_DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'CORE_JWT_PUBLIC_KEY_PATH'
              value: '/secrets/jwt-public.pem'
            }
            {
              name: 'CORE_JWKS_ISSUER'
              value: jwksIssuer
            }
            {
              name: 'CORE_JWKS_AUDIENCE'
              value: jwksAudience
            }
            {
              name: 'CORE_CORS_ORIGINS'
              value: string(corsOrigins)
            }
            {
              name: 'CORE_BASE_DOMAIN'
              value: baseDomain
            }
            {
              name: 'CORE_AI_AGENT_URL'
              // Short-form app name - resolves inside the CAE without
              // requiring the environment-unique FQDN suffix (no Bicep
              // cycle between core and ai-agent).
              value: 'http://app-ai-agent-${resourceName}'
            }
            {
              name: 'CORE_AI_SYNC_TOKEN'
              secretRef: 'sync-token'
            }
            {
              name: 'CORE_AI_INGEST_TOKEN'
              secretRef: 'ingest-token'
            }
            {
              name: 'CORE_DB_POOL_SIZE'
              value: string(dbPoolSize)
            }
            {
              name: 'CORE_DB_MAX_OVERFLOW'
              value: string(dbMaxOverflow)
            }
          ]
          probes: [
            {
              type: 'Readiness'
              httpGet: {
                path: '/api/v1/health'
                port: 8001
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              failureThreshold: 3
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/api/v1/health'
                port: 8001
              }
              initialDelaySeconds: 20
              periodSeconds: 30
              failureThreshold: 5
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-scale'
            http: {
              metadata: {
                concurrentRequests: string(concurrentRequests)
              }
            }
          }
        ]
      }
      volumes: [jwtVolumePublic]
    }
  }
}

// ---------------------------------------------------------------------------
// ai-agent - INTERNAL only, :8000
// ---------------------------------------------------------------------------

resource aiAgentApp 'Microsoft.App/containerApps@2026-01-01' = if (deployWorkloads) {
  name: 'app-ai-agent-${resourceName}'
  location: location
  tags: allTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uamiId}': {}
    }
  }
  properties: {
    environmentId: caeId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      registries: [
        {
          server: acrLoginServer
          identity: uamiId
        }
      ]
      maxInactiveRevisions: 5
      secrets: sharedSecrets
    }
    template: {
      containers: [
        {
          image: '${acrLoginServer}/ai-agent:${imageTag}'
          name: 'ai-agent'
          volumeMounts: [
            {
              volumeName: 'jwtkeys'
              mountPath: '/secrets'
            }
          ]
          resources: {
            cpu: json(containerCpu)
            memory: containerMemory
          }
          env: [
            {
              name: 'AI_ENVIRONMENT'
              value: appEnvironment
            }
            {
              name: 'AI_DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'AI_REDIS_URL'
              secretRef: 'redis-url'
            }
            {
              name: 'AI_JWT_PUBLIC_KEY_PATH'
              value: '/secrets/jwt-public.pem'
            }
            {
              name: 'AI_JWKS_ISSUER'
              value: jwksIssuer
            }
            {
              name: 'AI_JWKS_AUDIENCE'
              value: jwksAudience
            }
            {
              name: 'AI_CORS_ORIGINS'
              value: string(corsOrigins)
            }
            {
              name: 'AI_BASE_DOMAIN'
              value: baseDomain
            }
            {
              name: 'AI_INVENTORY_SERVICE_URL'
              value: 'http://app-core-${resourceName}'
            }
            {
              name: 'AI_REPORT_SERVICE_URL'
              value: 'http://app-core-${resourceName}'
            }
            {
              name: 'AI_CORE_DOCUMENT_URL'
              value: 'http://app-core-${resourceName}'
            }
            {
              name: 'AI_INGEST_TOKEN'
              secretRef: 'ingest-token'
            }
            {
              name: 'AI_INVENTORY_SYNC_TOKEN'
              secretRef: 'sync-token'
            }
            {
              name: 'AI_DOCUMENT_SYNC_TOKEN'
              secretRef: 'sync-token'
            }
            {
              name: 'AI_DB_POOL_SIZE'
              value: string(dbPoolSize)
            }
            {
              name: 'AI_DB_MAX_OVERFLOW'
              value: string(dbMaxOverflow)
            }
          ]
          probes: [
            {
              type: 'Readiness'
              httpGet: {
                path: '/api/v1/health'
                port: 8000
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              failureThreshold: 3
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/api/v1/health'
                port: 8000
              }
              initialDelaySeconds: 20
              periodSeconds: 30
              failureThreshold: 5
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-scale'
            http: {
              metadata: {
                concurrentRequests: string(concurrentRequests)
              }
            }
          }
        ]
      }
      volumes: [jwtVolumePublic]
    }
  }
}

// ---------------------------------------------------------------------------
// Diagnostic settings -> Log Analytics (console + system logs)
// ---------------------------------------------------------------------------

resource identityDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (deployWorkloads) {
  scope: identityApp
  name: 'diag-to-law-${resourceName}'
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        category: 'ContainerAppConsoleLogs'
        enabled: true
      }
      {
        category: 'ContainerAppSystemLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
        retentionPolicy: {
          enabled: false
          days: 0
        }
      }
    ]
  }
}

resource coreDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (deployWorkloads) {
  scope: coreApp
  name: 'diag-to-law-${resourceName}'
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        category: 'ContainerAppConsoleLogs'
        enabled: true
      }
      {
        category: 'ContainerAppSystemLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
        retentionPolicy: {
          enabled: false
          days: 0
        }
      }
    ]
  }
}

resource aiAgentDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (deployWorkloads) {
  scope: aiAgentApp
  name: 'diag-to-law-${resourceName}'
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        category: 'ContainerAppConsoleLogs'
        enabled: true
      }
      {
        category: 'ContainerAppSystemLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
        retentionPolicy: {
          enabled: false
          days: 0
        }
      }
    ]
  }
}

// ---------------------------------------------------------------------------
// db-init job - creates the shared database + extensions (idempotent)
// ---------------------------------------------------------------------------

var dbInitScript = '''
set -euo pipefail
if ! psql -v ON_ERROR_STOP=1 -tAc "SELECT 1 FROM pg_database WHERE datname = '$SKYRICT_DB'" | grep -q 1; then
  psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE $SKYRICT_DB"
fi
psql -d $SKYRICT_DB -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector"
psql -d $SKYRICT_DB -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS pg_trgm"
'''

resource dbInitJob 'Microsoft.App/jobs@2026-01-01' = if (deployWorkloads) {
  name: 'job-db-init-${resourceName}'
  location: location
  tags: allTags
  properties: {
    environmentId: caeId
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 300
      replicaRetryLimit: 2
      secrets: [
        {
          name: 'postgres-password'
          value: postgresPassword
        }
      ]
    }
    template: {
      containers: [
        {
          image: 'postgres:16-alpine'
          name: 'db-init'
          command: [
            '/bin/sh'
            '-c'
            dbInitScript
          ]
          env: [
            {
              name: 'PGHOST'
              value: postgresFqdn
            }
            {
              name: 'PGUSER'
              value: postgresLogin
            }
            {
              name: 'PGPASSWORD'
              secretRef: 'postgres-password'
            }
            {
              name: 'PGDATABASE'
              value: 'postgres'
            }
            {
              name: 'PGSSLMODE'
              value: 'require'
            }
            {
              name: 'SKYRICT_DB'
              value: postgresDbName
            }
          ]
          resources: {
            cpu: json(containerCpu)
            memory: containerMemory
          }
        }
      ]
    }
  }
}

// ---------------------------------------------------------------------------
// Migration jobs - one-shot, run by CD in this order: identity -> core -> ai
// ---------------------------------------------------------------------------

resource identityMigrateJob 'Microsoft.App/jobs@2026-01-01' = if (deployWorkloads) {
  name: 'job-identity-${resourceName}'
  location: location
  tags: allTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uamiId}': {}
    }
  }
  properties: {
    environmentId: caeId
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      replicaRetryLimit: 2
      registries: [
        {
          server: acrLoginServer
          identity: uamiId
        }
      ]
      secrets: sharedSecrets
    }
    template: {
      containers: [
        {
          image: '${acrLoginServer}/identity:${imageTag}'
          name: 'migrate'
          command: [
            'alembic'
            '-c'
            '/app/services/identity/alembic.ini'
            'upgrade'
            'head'
          ]
          volumeMounts: [
            {
              volumeName: 'jwtkeys'
              mountPath: '/secrets'
            }
          ]
          env: [
            {
              name: 'IDENTITY_ENVIRONMENT'
              value: appEnvironment
            }
            {
              name: 'IDENTITY_DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'IDENTITY_REDIS_URL'
              secretRef: 'redis-url'
            }
            {
              name: 'IDENTITY_JWT_PRIVATE_KEY_PATH'
              value: '/secrets/jwt-private.pem'
            }
            {
              name: 'IDENTITY_JWT_PUBLIC_KEY_PATH'
              value: '/secrets/jwt-public.pem'
            }
            {
              name: 'IDENTITY_MFA_ENCRYPTION_KEY'
              secretRef: 'mfa-encryption-key'
            }
            {
              name: 'IDENTITY_JWKS_ISSUER'
              value: jwksIssuer
            }
            {
              name: 'IDENTITY_JWKS_AUDIENCE'
              value: jwksAudience
            }
            {
              name: 'IDENTITY_BASE_DOMAIN'
              value: baseDomain
            }
          ]
          resources: {
            cpu: json(containerCpu)
            memory: containerMemory
          }
        }
      ]
      volumes: [jwtVolumeIdentity]
    }
  }
}

resource coreMigrateJob 'Microsoft.App/jobs@2026-01-01' = if (deployWorkloads) {
  name: 'job-core-${resourceName}'
  location: location
  tags: allTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uamiId}': {}
    }
  }
  properties: {
    environmentId: caeId
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      replicaRetryLimit: 2
      registries: [
        {
          server: acrLoginServer
          identity: uamiId
        }
      ]
      secrets: sharedSecrets
    }
    template: {
      containers: [
        {
          image: '${acrLoginServer}/core:${imageTag}'
          name: 'migrate'
          command: [
            'alembic'
            '-c'
            '/app/services/core/alembic.ini'
            'upgrade'
            'head'
          ]
          volumeMounts: [
            {
              volumeName: 'jwtkeys'
              mountPath: '/secrets'
            }
          ]
          env: [
            {
              name: 'CORE_ENVIRONMENT'
              value: appEnvironment
            }
            {
              name: 'CORE_DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'CORE_JWT_PUBLIC_KEY_PATH'
              value: '/secrets/jwt-public.pem'
            }
            {
              name: 'CORE_JWKS_ISSUER'
              value: jwksIssuer
            }
            {
              name: 'CORE_JWKS_AUDIENCE'
              value: jwksAudience
            }
            {
              name: 'CORE_BASE_DOMAIN'
              value: baseDomain
            }
          ]
          resources: {
            cpu: json(containerCpu)
            memory: containerMemory
          }
        }
      ]
      volumes: [jwtVolumePublic]
    }
  }
}

resource aiAgentMigrateJob 'Microsoft.App/jobs@2026-01-01' = if (deployWorkloads) {
  name: 'job-ai-agent-${resourceName}'
  location: location
  tags: allTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uamiId}': {}
    }
  }
  properties: {
    environmentId: caeId
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      replicaRetryLimit: 2
      registries: [
        {
          server: acrLoginServer
          identity: uamiId
        }
      ]
      secrets: sharedSecrets
    }
    template: {
      containers: [
        {
          image: '${acrLoginServer}/ai-agent:${imageTag}'
          name: 'migrate'
          command: [
            'alembic'
            '-c'
            '/app/services/ai-agent/alembic.ini'
            'upgrade'
            'head'
          ]
          volumeMounts: [
            {
              volumeName: 'jwtkeys'
              mountPath: '/secrets'
            }
          ]
          env: [
            {
              name: 'AI_ENVIRONMENT'
              value: appEnvironment
            }
            {
              name: 'AI_DATABASE_URL'
              secretRef: 'database-url'
            }
            {
              name: 'AI_REDIS_URL'
              secretRef: 'redis-url'
            }
            {
              name: 'AI_JWT_PUBLIC_KEY_PATH'
              value: '/secrets/jwt-public.pem'
            }
            {
              name: 'AI_JWKS_ISSUER'
              value: jwksIssuer
            }
            {
              name: 'AI_JWKS_AUDIENCE'
              value: jwksAudience
            }
            {
              name: 'AI_BASE_DOMAIN'
              value: baseDomain
            }
          ]
          resources: {
            cpu: json(containerCpu)
            memory: containerMemory
          }
        }
      ]
      volumes: [jwtVolumePublic]
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs (for main.bicep / CD / runbook)
// ---------------------------------------------------------------------------

output identityFqdn string = deployWorkloads ? identityApp!.properties.configuration.ingress.fqdn : ''
output coreFqdn string = deployWorkloads ? coreApp!.properties.configuration.ingress.fqdn : ''
output aiAgentFqdn string = deployWorkloads ? aiAgentApp!.properties.configuration.ingress.fqdn : ''
output dbInitJobName string = 'job-db-init-${resourceName}'
output identityMigrateJobName string = 'job-identity-${resourceName}'
output coreMigrateJobName string = 'job-core-${resourceName}'
output aiAgentMigrateJobName string = 'job-ai-agent-${resourceName}'
