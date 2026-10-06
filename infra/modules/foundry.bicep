@description('Foundry (AIServices) account name. Also used as the custom subdomain.')
param accountName string

@description('Foundry project name.')
param projectName string

param location string
param tags object = {}

@description('Model to deploy.')
param modelName string = 'gpt-5.6-luna'

@description('Model version.')
param modelVersion string = '2026-07-09'

@description('Deployment SKU, for example GlobalStandard or Standard.')
param modelSkuName string = 'GlobalStandard'

@description('Deployment capacity in thousands of tokens per minute.')
param modelCapacity int = 30

@description('Principal ID of the app-api managed identity (gets Azure AI User).')
param appApiPrincipalId string

@description('Principal ID of the deployer (gets Azure AI User so deploy_agent.py can publish the agent). Empty skips.')
param deployerPrincipalId string = ''

@allowed([
  'User'
  'Group'
  'ServicePrincipal'
])
param deployerPrincipalType string = 'User'

@description('Principal ID of the CI pipeline identity (gets Azure AI User so the deploy workflow can publish the agent). Empty skips.')
param pipelinePrincipalId string = ''

@description('Application Insights resource ID. Connected to the account so Foundry Tracing shows agent traces.')
param applicationInsightsId string = ''

@secure()
@description('Application Insights connection string (stored as the connection credential).')
param applicationInsightsConnectionString string = ''

var azureAiUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: projectName
    description: 'Energy usage agent POC project'
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: modelName
  sku: {
    name: modelSkuName
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
  // Avoid concurrent writes on the account.
  dependsOn: [
    project
  ]
}

resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/connections@2025-06-01' = if (!empty(applicationInsightsId)) {
  parent: account
  name: 'appinsights'
  properties: {
    category: 'AppInsights'
    target: applicationInsightsId
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: {
      key: applicationInsightsConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: applicationInsightsId
    }
  }
  dependsOn: [
    modelDeployment
  ]
}

resource appApiAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, appApiPrincipalId, azureAiUserRoleId)
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiUserRoleId)
    principalId: appApiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Foundry evaluations call the judge model with the project's managed identity.
resource projectAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, project.id, azureAiUserRoleId)
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiUserRoleId)
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(account.id, deployerPrincipalId, azureAiUserRoleId)
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiUserRoleId)
    principalId: deployerPrincipalId
    principalType: deployerPrincipalType
  }
}

resource pipelineAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(pipelinePrincipalId)) {
  name: guid(account.id, pipelinePrincipalId, azureAiUserRoleId)
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiUserRoleId)
    principalId: pipelinePrincipalId
    principalType: 'ServicePrincipal'
  }
}

output accountId string = account.id
output accountName string = account.name
output projectName string = project.name
output projectEndpoint string = 'https://${account.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'
output modelDeploymentName string = modelDeployment.name
