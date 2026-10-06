@description('PostgreSQL Flexible Server name.')
param name string

param location string
param tags object = {}

@description('Database created on the server.')
param databaseName string = 'energy'

@description('PostgreSQL major version.')
param version string = '16'

@description('Object ID of the Entra principal that becomes the Postgres Entra administrator (the deployer). Empty skips the admin.')
param adminPrincipalId string = ''

@description('Name of the Entra administrator: UPN for a user, display name for a service principal or group.')
param adminPrincipalName string = ''

@allowed([
  'User'
  'Group'
  'ServicePrincipal'
])
param adminPrincipalType string = 'User'

@description('Optional public IP of the deployer (dev box) for migrations and seed. Empty skips the rule.')
param clientIpAddress string = ''

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: version
    // Entra-only: no administratorLogin / password anywhere.
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Disabled'
      tenantId: tenant().tenantId
    }
    storage: {
      storageSizeGB: 32
      autoGrow: 'Disabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      publicNetworkAccess: 'Enabled'
    }
  }
}

// Flexible Server rejects concurrent child operations, so the children below are chained with dependsOn.
resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: server
  name: databaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// POC only: allows any Azure-hosted source (including Container Apps outbound). Replace with private networking later.
resource allowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: server
  name: 'AllowAllAzureServicesAndResourcesWithinAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
  dependsOn: [
    database
  ]
}

resource allowClientIp 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = if (!empty(clientIpAddress)) {
  parent: server
  name: 'AllowDeployerClientIp'
  properties: {
    startIpAddress: clientIpAddress
    endIpAddress: clientIpAddress
  }
  dependsOn: [
    allowAzure
  ]
}

resource entraAdmin 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-08-01' = if (!empty(adminPrincipalId) && !empty(adminPrincipalName)) {
  parent: server
  name: adminPrincipalId
  properties: {
    principalName: adminPrincipalName
    principalType: adminPrincipalType
    tenantId: tenant().tenantId
  }
  dependsOn: [
    allowAzure
    allowClientIp
  ]
}

output id string = server.id
output name string = server.name
output fqdn string = server.properties.fullyQualifiedDomainName
output databaseName string = database.name
