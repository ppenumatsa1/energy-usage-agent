targetScope = 'subscription'

// ---------------------------------------------------------------------------
// Core
// ---------------------------------------------------------------------------
@minLength(1)
@maxLength(64)
@description('azd environment name. Drives the resource group name and the unique resource token.')
param environmentName string

@minLength(1)
@description('Primary location for all resources.')
param location string

@description('Optional location override for the Foundry account (model availability differs by region). Empty = location.')
param aiLocation string = ''

@description('Optional location override for PostgreSQL (regions can run out of Burstable capacity: SkuNotAvailable). Empty = location.')
param postgresLocation string = ''

// ---------------------------------------------------------------------------
// Deployer (becomes Postgres Entra admin and gets Azure AI User on Foundry)
// ---------------------------------------------------------------------------
@description('Object ID of the deployer principal. azd fills this from AZURE_PRINCIPAL_ID.')
param principalId string = ''

@description('Deployer name for the Postgres Entra admin: UPN for a user, display name for a service principal. Empty skips the Postgres admin.')
param principalName string = ''

@allowed([
  'User'
  'Group'
  'ServicePrincipal'
])
param principalType string = 'User'

@description('Optional public IP of the dev box, added as a Postgres firewall rule for migrations/seed.')
param clientIpAddress string = ''

@description('Object ID of the CI pipeline identity (scripts/setup_ci.py). It deploys code only, so it just needs Azure AI User to publish the agent. Empty skips.')
param pipelinePrincipalId string = ''

// ---------------------------------------------------------------------------
// Entra app registrations (created here, see modules/entra.bicep)
// ---------------------------------------------------------------------------
@description('Dev only: pre-authorize the Azure CLI on Chat.Ask so scripts can get user tokens. Set false for production.')
param preauthorizeAzureCli bool = true

// ---------------------------------------------------------------------------
// Foundry model
// ---------------------------------------------------------------------------
param modelName string = 'gpt-5.6-luna'
param modelVersion string = '2026-07-09'
param modelSkuName string = 'GlobalStandard'
param modelCapacity int = 30

@description('Record message content (questions, answers, tool results) in GenAI traces (App Insights + Foundry Tracing). Off by default; turn on only for synthetic data.')
param traceContent bool = false

// ---------------------------------------------------------------------------
// azd image persistence: azd sets SERVICE_<NAME>_RESOURCE_EXISTS before provision.
// When true, the currently running image is reused so re-provision does not reset it.
// ---------------------------------------------------------------------------
param webExists bool = false
param appApiExists bool = false
param energyServiceExists bool = false

// ---------------------------------------------------------------------------
// Names
// ---------------------------------------------------------------------------
var abbrs = loadJsonContent('abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = {
  'azd-env-name': environmentName
}
var databaseName = 'energy'
var foundryAgentName = 'energy-usage-agent'

var webAppName = '${abbrs.appContainerApps}web-${resourceToken}'
var appApiAppName = '${abbrs.appContainerApps}app-api-${resourceToken}'
var energyServiceAppName = '${abbrs.appContainerApps}energy-service-${resourceToken}'

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: '${abbrs.resourcesResourceGroups}${environmentName}'
  location: location
  tags: tags
}

// ---------------------------------------------------------------------------
// Shared platform
// ---------------------------------------------------------------------------
module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: rg
  params: {
    logAnalyticsName: '${abbrs.operationalInsightsWorkspaces}${resourceToken}'
    applicationInsightsName: '${abbrs.insightsComponents}${resourceToken}'
    location: location
    tags: tags
  }
}

module registry 'modules/registry.bicep' = {
  name: 'registry'
  scope: rg
  params: {
    name: '${abbrs.containerRegistryRegistries}${resourceToken}'
    location: location
    tags: tags
  }
}

module webIdentity 'modules/identity.bicep' = {
  name: 'identity-web'
  scope: rg
  params: {
    name: '${abbrs.managedIdentityUserAssignedIdentities}web-${resourceToken}'
    location: location
    tags: tags
    registryName: registry.outputs.name
  }
}

module appApiIdentity 'modules/identity.bicep' = {
  name: 'identity-app-api'
  scope: rg
  params: {
    name: '${abbrs.managedIdentityUserAssignedIdentities}app-api-${resourceToken}'
    location: location
    tags: tags
    registryName: registry.outputs.name
  }
}

module energyServiceIdentity 'modules/identity.bicep' = {
  name: 'identity-energy-service'
  scope: rg
  params: {
    name: '${abbrs.managedIdentityUserAssignedIdentities}energy-service-${resourceToken}'
    location: location
    tags: tags
    registryName: registry.outputs.name
  }
}

module postgres 'modules/postgres.bicep' = {
  name: 'postgres'
  scope: rg
  params: {
    // An override gets its own name: a server that failed in the first region can block the name there.
    name: empty(postgresLocation) ? '${abbrs.dBforPostgreSQLServers}${resourceToken}' : '${abbrs.dBforPostgreSQLServers}${resourceToken}-${postgresLocation}'
    location: empty(postgresLocation) ? location : postgresLocation
    tags: tags
    databaseName: databaseName
    adminPrincipalId: principalId
    adminPrincipalName: principalName
    adminPrincipalType: principalType
    clientIpAddress: clientIpAddress
  }
}

module foundry 'modules/foundry.bicep' = {
  name: 'foundry'
  scope: rg
  params: {
    accountName: '${abbrs.cognitiveServicesAIServices}${resourceToken}'
    projectName: '${abbrs.cognitiveServicesProjects}${resourceToken}'
    location: empty(aiLocation) ? location : aiLocation
    tags: tags
    modelName: modelName
    modelVersion: modelVersion
    modelSkuName: modelSkuName
    modelCapacity: modelCapacity
    appApiPrincipalId: appApiIdentity.outputs.principalId
    deployerPrincipalId: principalId
    deployerPrincipalType: principalType
    pipelinePrincipalId: pipelinePrincipalId
    applicationInsightsId: monitoring.outputs.applicationInsightsId
    applicationInsightsConnectionString: monitoring.outputs.applicationInsightsConnectionString
  }
}

module containerAppsEnvironment 'modules/aca-env.bicep' = {
  name: 'aca-env'
  scope: rg
  params: {
    name: '${abbrs.appManagedEnvironments}${resourceToken}'
    location: location
    tags: tags
    logAnalyticsWorkspaceName: monitoring.outputs.logAnalyticsWorkspaceName
  }
}

module entra 'modules/entra.bicep' = {
  name: 'entra'
  scope: rg
  params: {
    prefix: 'energy-usage'
    suffix: resourceToken
    environmentName: environmentName
    // Known before the web app exists, so the registrations and the apps deploy in one pass.
    webUrl: 'https://${webAppName}.${containerAppsEnvironment.outputs.defaultDomain}'
    appApiIdentityPrincipalId: appApiIdentity.outputs.principalId
    ownerIds: empty(principalId) ? [] : [principalId]
    preauthorizeAzureCli: preauthorizeAzureCli
  }
}

// ---------------------------------------------------------------------------
// Existing apps (only read when azd reports they exist) -> keep the deployed image
// ---------------------------------------------------------------------------
resource webExisting 'Microsoft.App/containerApps@2025-01-01' existing = if (webExists) {
  scope: rg
  name: webAppName
}

resource appApiExisting 'Microsoft.App/containerApps@2025-01-01' existing = if (appApiExists) {
  scope: rg
  name: appApiAppName
}

resource energyServiceExisting 'Microsoft.App/containerApps@2025-01-01' existing = if (energyServiceExists) {
  scope: rg
  name: energyServiceAppName
}

// ---------------------------------------------------------------------------
// Container apps
// ---------------------------------------------------------------------------
module energyService 'modules/container-app.bicep' = {
  name: 'app-energy-service'
  scope: rg
  params: {
    name: energyServiceAppName
    location: location
    tags: union(tags, { 'azd-service-name': 'energy-service' })
    environmentId: containerAppsEnvironment.outputs.id
    image: energyServiceExists ? energyServiceExisting!.properties.template!.containers![0].image! : ''
    targetPort: 8000
    external: false
    identityId: energyServiceIdentity.outputs.id
    registryServer: registry.outputs.loginServer
    probePath: '/healthz'
    env: [
      { name: 'ENVIRONMENT', value: 'azure' }
      { name: 'AUTH_MODE', value: 'entra' }
      { name: 'AUTH_AUDIENCE', value: entra.outputs.energyServiceAppId }
      { name: 'AUTH_TENANT_ID', value: tenant().tenantId }
      { name: 'AUTH_REQUIRED_SCOPE', value: 'Energy.Read' }
      { name: 'AUTH_ALLOWED_CLIENT_IDS', value: entra.outputs.appApiAppId }
      { name: 'DB_HOST', value: postgres.outputs.fqdn }
      { name: 'DB_NAME', value: databaseName }
      { name: 'DB_USER', value: energyServiceIdentity.outputs.name }
      { name: 'DB_ENTRA_AUTH', value: 'true' }
      { name: 'AZURE_CLIENT_ID', value: energyServiceIdentity.outputs.clientId }
      { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: monitoring.outputs.applicationInsightsConnectionString }
    ]
  }
}

module appApi 'modules/container-app.bicep' = {
  name: 'app-app-api'
  scope: rg
  params: {
    name: appApiAppName
    location: location
    tags: union(tags, { 'azd-service-name': 'app-api' })
    environmentId: containerAppsEnvironment.outputs.id
    image: appApiExists ? appApiExisting!.properties.template!.containers![0].image! : ''
    targetPort: 8000
    external: false
    identityId: appApiIdentity.outputs.id
    registryServer: registry.outputs.loginServer
    probePath: '/healthz'
    env: [
      { name: 'ENVIRONMENT', value: 'azure' }
      { name: 'AUTH_MODE', value: 'entra' }
      { name: 'AUTH_AUDIENCE', value: entra.outputs.appApiAppId }
      { name: 'AUTH_TENANT_ID', value: tenant().tenantId }
      { name: 'AUTH_REQUIRED_SCOPE', value: 'Chat.Ask' }
      { name: 'AUTH_ALLOWED_CLIENT_IDS', value: entra.outputs.appApiClientIds }
      { name: 'ENERGY_SERVICE_URL', value: energyService.outputs.uri }
      { name: 'ENERGY_SERVICE_SCOPE', value: entra.outputs.energyServiceScope }
      { name: 'ENTRA_CLIENT_ID', value: entra.outputs.appApiAppId }
      { name: 'OBO_CREDENTIAL', value: 'federated' }
      { name: 'AZURE_CLIENT_ID', value: appApiIdentity.outputs.clientId }
      { name: 'AGENT_MODE', value: 'foundry' }
      { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundry.outputs.projectEndpoint }
      { name: 'FOUNDRY_AGENT_NAME', value: foundryAgentName }
      { name: 'APP_DB_HOST', value: postgres.outputs.fqdn }
      { name: 'APP_DB_NAME', value: databaseName }
      { name: 'APP_DB_USER', value: appApiIdentity.outputs.name }
      { name: 'APP_DB_ENTRA_AUTH', value: 'true' }
      { name: 'RATE_LIMIT_PER_MINUTE', value: '20' }
      { name: 'HISTORY_RETENTION_DAYS', value: '30' }
      { name: 'AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING', value: 'true' }
      { name: 'OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT', value: string(traceContent) }
      { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: monitoring.outputs.applicationInsightsConnectionString }
    ]
  }
}

module web 'modules/container-app.bicep' = {
  name: 'app-web'
  scope: rg
  params: {
    name: webAppName
    location: location
    tags: union(tags, { 'azd-service-name': 'web' })
    environmentId: containerAppsEnvironment.outputs.id
    image: webExists ? webExisting!.properties.template!.containers![0].image! : ''
    targetPort: 8080
    external: true
    identityId: webIdentity.outputs.id
    registryServer: registry.outputs.loginServer
    probePath: '/'
    env: [
      { name: 'APP_API_URL', value: appApi.outputs.uri }
      { name: 'AUTH_MODE', value: 'entra' }
      { name: 'ENTRA_CLIENT_ID', value: entra.outputs.webAppId }
      { name: 'ENTRA_AUTHORITY', value: '${environment().authentication.loginEndpoint}${tenant().tenantId}' }
      { name: 'API_SCOPE', value: entra.outputs.apiScope }
    ]
  }
}

// ---------------------------------------------------------------------------
// Outputs (azd writes these into the environment)
// ---------------------------------------------------------------------------
output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.outputs.loginServer
output AZURE_CONTAINER_REGISTRY_NAME string = registry.outputs.name
output AZURE_CONTAINER_ENVIRONMENT_NAME string = containerAppsEnvironment.outputs.name
output AZURE_AI_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output AZURE_AI_ACCOUNT_NAME string = foundry.outputs.accountName
output AZURE_AI_PROJECT_NAME string = foundry.outputs.projectName
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = foundry.outputs.modelDeploymentName
output APPLICATIONINSIGHTS_NAME string = monitoring.outputs.applicationInsightsName
output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.applicationInsightsConnectionString
output POSTGRES_HOST string = postgres.outputs.fqdn
output POSTGRES_DATABASE string = postgres.outputs.databaseName
output POSTGRES_ADMIN_USER string = principalName
output ENERGY_SERVICE_IDENTITY_NAME string = energyServiceIdentity.outputs.name
output ENERGY_SERVICE_IDENTITY_CLIENT_ID string = energyServiceIdentity.outputs.clientId
output APP_API_IDENTITY_NAME string = appApiIdentity.outputs.name
output APP_API_IDENTITY_CLIENT_ID string = appApiIdentity.outputs.clientId
output APP_API_IDENTITY_PRINCIPAL_ID string = appApiIdentity.outputs.principalId
output APP_API_URL string = appApi.outputs.uri
output ENERGY_SERVICE_URL string = energyService.outputs.uri
output FRONTEND_URL string = web.outputs.uri
output WEB_APP_ID string = entra.outputs.webAppId
output APP_API_APP_ID string = entra.outputs.appApiAppId
output ENERGY_SERVICE_APP_ID string = entra.outputs.energyServiceAppId
output API_SCOPE string = entra.outputs.apiScope
output ENERGY_SERVICE_SCOPE string = entra.outputs.energyServiceScope
