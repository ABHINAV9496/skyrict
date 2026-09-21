// =============================================================================
// SKY-114 - Data module
//
// PostgreSQL Flexible Server (private VNet access, shared `skyrict_identity`
// database for identity/core/ai-agent, each under its own Alembic version
// table) and - while `deployManagedRedis` is true (month 1) - Azure Cache
// for Redis Standard C0 reached only over a private endpoint with
// publicNetworkAccess disabled.
//
// Redis is CONDITIONAL on purpose: the beta rides the 30-day trial/Azure
// managed Redis for month 1, then swaps to a config-only switch
// (deployManagedRedis=false + redisUrlOverride -> Upstash Serverless Redis
// free tier) so steady-state costs $0/month. The app code is unchanged
// because both endpoints speak redis:// with TLS.
//
// Cost posture:
//   postgresSku  -> Standard_B1ms (Burstable) - included in the Azure free
//                   account's 12-month compute (750 h/month).
//   storage 32GB -> within the 12-month free storage allotment.
//   redis C0      -> minimal-cost during month 1; removed after the swap.
//
// Secrets are NOT created here: the administrator password arrives as a
// @secure() parameter and is used to build the ACA secret store in
// apps.bicep. No secret value ever appears in a Bicep output.
// =============================================================================

@description('Resource name prefix. Defaults to "skyrict".')
param prefix string = 'skyrict'

@description('Deployment environment name (beta/staging/production).')
param envName string

@description('Azure region for all resources.')
param location string

@description('Tags merged onto every resource.')
param tags object = {}

@description('Resource ID of the VNet the resources join.')
param vnetId string

@description('Resource ID of the subnet delegated to Microsoft.DBforPostgreSQL/flexibleServers.')
param postgresSubnetId string

@description('Resource ID of the private-endpoint subnet.')
param peSubnetId string

@description('Flexible Server administrator login.')
param postgresLogin string = 'skyrict'

@secure()
@description('Flexible Server administrator password. Bicep never logs or outputs it.')
param postgresPassword string

@description('Flexible Server compute SKU - Standard_B1ms is the 12-month free tier.')
param postgresSku string = 'Standard_B1ms'

@description('Flexible Server SKU tier (Burstable for the free-tier SKU).')
param postgresSkuTier string = 'Burstable'

@description('PostgreSQL major version - 16 matches the CI image (postgres:16).')
@allowed([
  '15'
  '16'
  '17'
])
param postgresVersion string = '16'

@description('Storage size in GB - 32 is the 12-month free allotment.')
@minValue(32)
@maxValue(1024)
param postgresStorageGB int = 32

@description('Backup retention in days.')
@minValue(7)
@maxValue(35)
param backupRetentionDays int = 7

@description('Name of the shared application database inside the server.')
param postgresDbName string = 'skyrict_identity'

@description('Deploy the managed Azure Cache for Redis (true for month 1; false after the Upstash swap).')
param deployManagedRedis bool = true

@description('Azure Cache for Redis SKU family/name (C0 = Standard tier, 250 MB).')
@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param redisSku string = 'Standard'

@description('Azure Cache for Redis capacity for the SKU (0 = C0 for Basic/Standard).')
param redisCapacity int = 0

var allTags = union(
  {
    environment: envName
    service: prefix
    managedBy: 'bicep'
  },
  tags
)

var resourceName = '${prefix}-${envName}'
var postgresName = 'pg-${resourceName}'
// Azure Cache for Redis names allow only lowercase letters and digits.
var redisName = 'redis${prefix}${envName}'

// ---------------------------------------------------------------------------
// PostgreSQL Flexible Server (private access: delegated subnet + private DNS)
// ---------------------------------------------------------------------------

resource postgresZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.postgres.database.azure.com'
  location: 'global'
}

resource postgresZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: postgresZone
  name: 'link-${resourceName}'
  location: 'global'
  properties: {
    virtualNetwork: {
      id: vnetId
    }
    registrationEnabled: false
  }
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: postgresName
  location: location
  tags: allTags
  sku: {
    name: postgresSku
    tier: postgresSkuTier
  }
  properties: {
    version: postgresVersion
    administratorLogin: postgresLogin
    administratorLoginPassword: postgresPassword
    authConfig: {
      activeDirectoryAuth: 'Disabled'
      passwordAuth: 'Enabled'
    }
    storage: {
      storageSizeGB: postgresStorageGB
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: backupRetentionDays
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      delegatedSubnetResourceId: postgresSubnetId
      privateDnsZoneArmResourceId: postgresZone.id
    }
  }
}

// ---------------------------------------------------------------------------
// Azure Cache for Redis (conditional - month 1 only)
// ---------------------------------------------------------------------------

resource redisZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (deployManagedRedis) {
  name: 'privatelink.redis.cache.windows.net'
  location: 'global'
}

resource redisZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (deployManagedRedis) {
  parent: redisZone
  name: 'link-${resourceName}'
  location: 'global'
  properties: {
    virtualNetwork: {
      id: vnetId
    }
    registrationEnabled: false
  }
}

resource redis 'Microsoft.Cache/redis@2024-03-01' = if (deployManagedRedis) {
  name: redisName
  location: location
  tags: allTags
  properties: {
    sku: {
      name: redisSku
      family: 'C'
      capacity: redisCapacity
    }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
  }
}

resource redisPe 'Microsoft.Network/privateEndpoints@2023-06-01' = if (deployManagedRedis) {
  name: 'pe-${redisName}'
  location: location
  tags: allTags
  properties: {
    subnet: {
      id: peSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-${redisName}-connection'
        properties: {
          privateLinkServiceId: redis.id
          groupIds: [
            'redis'
          ]
        }
      }
    ]
  }
}

resource redisPeDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-06-01' = if (deployManagedRedis) {
  parent: redisPe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'redis'
        properties: {
          privateDnsZoneId: redisZone.id
        }
      }
    ]
  }
}

// ---------------------------------------------------------------------------
// Outputs (never secret-bearing; apps.bicep computes the Redis URL itself)
// ---------------------------------------------------------------------------

output postgresFqdn string = postgres.properties.fullyQualifiedDomainName
output postgresName string = postgres.name
output postgresDbName string = postgresDbName
output postgresLogin string = postgresLogin
output redisName string = deployManagedRedis ? redisName : ''
output redisId string = deployManagedRedis ? redis.id : ''
