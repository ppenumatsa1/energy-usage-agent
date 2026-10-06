@description('Container app name (max 32 chars, lowercase letters, digits and hyphens).')
param name string

param location string
param tags object = {}

@description('Container Apps environment resource ID.')
param environmentId string

@description('Image to run. Empty uses the placeholder image (first provision, before azd deploy pushes a real one).')
param image string = ''

@description('Port the container listens on.')
param targetPort int

@description('true = public ingress; false = reachable only inside the Container Apps environment.')
param external bool = false

@description('Environment variables: [{ name, value }].')
param env array = []

@description('Resource ID of the user-assigned managed identity used for the app and for ACR pulls.')
param identityId string

@description('ACR login server, for example myregistry.azurecr.io.')
param registryServer string

@description('HTTP path for liveness, readiness and startup probes.')
param probePath string = '/healthz'

param cpu string = '0.5'
param memory string = '1Gi'
param minReplicas int = 1
param maxReplicas int = 3

var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var containerImage = empty(image) ? placeholderImage : image

resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: external
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: registryServer
          identity: identityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'main'
          image: containerImage
          env: env
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: probePath
                port: targetPort
              }
              initialDelaySeconds: 3
              periodSeconds: 5
              failureThreshold: 24
            }
            {
              type: 'Readiness'
              httpGet: {
                path: probePath
                port: targetPort
              }
              periodSeconds: 10
              failureThreshold: 3
            }
            {
              type: 'Liveness'
              httpGet: {
                path: probePath
                port: targetPort
              }
              periodSeconds: 15
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

output id string = app.id
output name string = app.name
@description('Ingress FQDN. For internal apps this is <name>.internal.<environment default domain>.')
output fqdn string = app.properties.configuration.ingress.fqdn
output uri string = 'https://${app.properties.configuration.ingress.fqdn}'
