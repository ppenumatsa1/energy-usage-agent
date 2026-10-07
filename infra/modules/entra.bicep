// The three Entra app registrations (single tenant), created with the Microsoft Graph Bicep extension.
//
//   web             SPA. Signs users in; redirect URIs = the web container app + local Vite.
//   app-api         Exposes Chat.Ask, pre-authorizes web. Federated credential = the app-api managed identity (no secret).
//   energy-service  Exposes Energy.Read, pre-authorizes app-api (OBO without consent).
//
// Pre-authorization replaces consent and requiredResourceAccess, so the chain is one-way (no cycle):
// web -> app-api -> energy-service. Guests are invited by the tenant admin, never by this app (docs/auth-flow.md).
extension 'br:mcr.microsoft.com/bicep/extensions/microsoftgraph/v1.0:1.0.0'

@description('Prefix for display and unique names, e.g. energy-usage.')
param prefix string

@description('Suffix that keeps names unique per environment (the resource token).')
param suffix string

@description('azd environment name, shown in display names.')
param environmentName string

@description('Public URL of the web container app (SPA redirect URI).')
param webUrl string

@description('Principal ID of the app-api user-assigned managed identity (federated credential subject).')
param appApiIdentityPrincipalId string

@description('Object IDs added as owners of all three apps (the deployer).')
param ownerIds array = []

@description('Dev only: pre-authorize the Azure CLI on Chat.Ask so scripts can get user tokens with `az account get-access-token`.')
param preauthorizeAzureCli bool = false

var tenantId = tenant().tenantId
var localRedirect = 'http://localhost:5173'
var azureCliClientId = '04b07795-8ddb-461a-bbee-02f9e1bf7b46' // well-known public client
var owners = { relationshipSemantics: 'append', relationships: ownerIds }

var webName = '${prefix}-web-${suffix}'
var apiName = '${prefix}-app-api-${suffix}'
var energyName = '${prefix}-energy-service-${suffix}'
var chatScopeId = guid(tenantId, apiName, 'Chat.Ask')
var energyScopeId = guid(tenantId, energyName, 'Energy.Read')

// api://<tenant>/<name> is allowed by both tenant identifier-URI policies (v2 tokens; unique tenant identifier).
var apiUri = 'api://${tenantId}/${apiName}'
var energyUri = 'api://${tenantId}/${energyName}'

func scope(id string, value string, description string) object => {
  id: id
  value: value
  type: 'User'
  isEnabled: true
  adminConsentDisplayName: description
  adminConsentDescription: description
  userConsentDisplayName: description
  userConsentDescription: description
}

resource web 'Microsoft.Graph/applications@v1.0' = {
  uniqueName: webName
  displayName: '${prefix}-web (${environmentName})'
  signInAudience: 'AzureADMyOrg'
  spa: {
    redirectUris: [webUrl, localRedirect]
  }
  owners: owners
}

resource webSp 'Microsoft.Graph/servicePrincipals@v1.0' = {
  appId: web.appId
}

resource api 'Microsoft.Graph/applications@v1.0' = {
  uniqueName: apiName
  displayName: '${prefix}-app-api (${environmentName})'
  signInAudience: 'AzureADMyOrg'
  identifierUris: [apiUri]
  api: {
    requestedAccessTokenVersion: 2
    oauth2PermissionScopes: [scope(chatScopeId, 'Chat.Ask', 'Ask the energy usage assistant')]
    preAuthorizedApplications: concat(
      [{ appId: web.appId, delegatedPermissionIds: [chatScopeId] }],
      preauthorizeAzureCli ? [{ appId: azureCliClientId, delegatedPermissionIds: [chatScopeId] }] : []
    )
  }
  owners: owners

  resource managedIdentityCredential 'federatedIdentityCredentials@v1.0' = {
    name: '${api.uniqueName}/app-api-managed-identity'
    description: 'app-api container app identity (OBO client assertion)'
    audiences: ['api://AzureADTokenExchange']
    issuer: '${environment().authentication.loginEndpoint}${tenantId}/v2.0'
    subject: appApiIdentityPrincipalId
  }
}

resource apiSp 'Microsoft.Graph/servicePrincipals@v1.0' = {
  appId: api.appId
}

resource energy 'Microsoft.Graph/applications@v1.0' = {
  uniqueName: energyName
  displayName: '${prefix}-energy-service (${environmentName})'
  signInAudience: 'AzureADMyOrg'
  identifierUris: [energyUri]
  api: {
    requestedAccessTokenVersion: 2
    oauth2PermissionScopes: [scope(energyScopeId, 'Energy.Read', 'Read your organization\'s energy usage')]
    preAuthorizedApplications: [
      {
        appId: api.appId
        delegatedPermissionIds: [energyScopeId]
      }
    ]
  }
  owners: owners
}

resource energySp 'Microsoft.Graph/servicePrincipals@v1.0' = {
  appId: energy.appId
}

output webAppId string = web.appId
output appApiAppId string = api.appId
output energyServiceAppId string = energy.appId
@description('Clients allowed to call app-api (checked against the token `azp`): the web app, plus the Azure CLI when pre-authorized.')
output appApiClientIds string = join(concat([web.appId], preauthorizeAzureCli ? [azureCliClientId] : []), ',')
output apiScope string = '${apiUri}/Chat.Ask'
output energyServiceScope string = '${energyUri}/Energy.Read'
