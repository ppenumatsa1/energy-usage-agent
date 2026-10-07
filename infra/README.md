# Infrastructure (Bicep + azd)

`azd` provisions `main.bicep` at subscription scope. It creates the resource group `rg-<AZURE_ENV_NAME>` and everything below inside it. Resource names use `abbreviations.json` plus `uniqueString(subscription().id, environmentName, location)`.

## What gets created
| Module | Resources |
|---|---|
| `modules/monitoring.bicep` | Log Analytics workspace, workspace-based Application Insights |
| `modules/registry.bicep` | Azure Container Registry (Basic, admin user off) |
| `modules/keyvault.bicep` | Key Vault (RBAC mode, no secrets or role assignments by default) |
| `modules/identity.bicep` | One user-assigned managed identity + AcrPull on the registry. Used 3 times: web, app-api, energy-service |
| `modules/postgres.bicep` | PostgreSQL Flexible Server 16, Burstable B1ms, **Entra-only auth** (password auth disabled), database `energy`, firewall rules, Entra admin = deployer |
| `modules/foundry.bicep` | Foundry account (`AIServices`, `allowProjectManagement`, custom subdomain, local auth off), project, model deployment, App Insights connection (portal Tracing tab), "Azure AI User" for app-api identity, deployer and the project identity (cloud evaluations) |
| `modules/aca-env.bicep` | Container Apps environment (workload profiles, Consumption only), logs to Log Analytics |
| `modules/entra.bicep` | The 3 Entra app registrations + service principals (Microsoft Graph Bicep extension), see below |
| `modules/container-app.bicep` | Generic container app: user-assigned identity, ACR pull through that identity, 1–3 replicas, HTTP startup/readiness/liveness probes |

Container apps:
| azd service | Ingress | Port | Probe |
|---|---|---|---|
| `web` | **external** (the only public app) | 8080 | `/` |
| `app-api` | internal (the frontend's nginx proxies same-origin `/api` to it) | 8000 | `/healthz` |
| `energy-service` | internal | 8000 | `/healthz` |

Internal apps are reachable only from inside the environment at `https://<app>.internal.<env-domain>`. The nginx proxy must send SNI and the upstream host (`proxy_ssl_server_name on;` and `proxy_set_header Host <app-api host>`).

## Parameters
Set them with `azd env set <NAME> <value>`. `main.parameters.json` maps each one to a Bicep parameter.

| azd env variable | Bicep param | Required | Notes |
|---|---|---|---|
| `AZURE_ENV_NAME` | `environmentName` | yes | Set by `azd init` / `azd env new` |
| `AZURE_LOCATION` | `location` | yes | Pick a region with Postgres Flexible Server B-series capacity and your model |
| `AZURE_PRINCIPAL_ID` | `principalId` | auto | azd fills it from the signed-in principal |
| `AZURE_PRINCIPAL_NAME` | `principalName` | auto | Postgres Entra admin name (your UPN). Set by `scripts/preflight.py` |
| `AZURE_PRINCIPAL_TYPE` | `principalType` | auto | `User` (provisioning is done by a person). Set by `scripts/preflight.py` |
| `CLIENT_IP_ADDRESS` | `clientIpAddress` | auto | The deployer's public IPv4, for the Postgres firewall rule. Set by `scripts/preflight.py` |
| `AZURE_AI_LOCATION` | `aiLocation` | no | Foundry region override when the model isn't available in `AZURE_LOCATION` |
| `AZURE_PIPELINE_PRINCIPAL_ID` | `pipelinePrincipalId` | no | Object ID of the CI identity; gets Azure AI User on Foundry so CI can publish the agent. Set by `scripts/setup_ci.py` |
| `ENTRA_PREAUTHORIZE_AZURE_CLI` | `preauthorizeAzureCli` | no | Default `true`: the Azure CLI may get user tokens for `Chat.Ask`, so scripts can test as you. Set `false` outside dev |
| `AZURE_AI_MODEL_NAME` / `_VERSION` / `_SKU` / `_CAPACITY` | `modelName` / `modelVersion` / `modelSkuName` / `modelCapacity` | no | Defaults `gpt-5.6-luna` / `2026-07-09` / `GlobalStandard` / `30` (K TPM). Check quota first |
| `TRACE_CONTENT` | `traceContent` | no | Default `false`. `true` puts message content (questions, answers, tool result rows) in GenAI spans; use only with synthetic data (`azd env set TRACE_CONTENT true`, then `azd provision`) |
| `SERVICE_<NAME>_RESOURCE_EXISTS` | `webExists` / `appApiExists` / `energyServiceExists` | auto | Set by azd before each provision, see below |

### App registrations (`modules/entra.bicep`)
Created and updated by every `azd provision` with the [Microsoft Graph Bicep extension](https://learn.microsoft.com/graph/templates/bicep/overview-bicep-templates-for-graph):
| App (`uniqueName` = `energy-usage-<role>-<token>`) | Exposes | Pre-authorized clients | Notes |
|---|---|---|---|
| web (SPA) | — | — | Redirect URIs: `FRONTEND_URL`, `http://localhost:5173` |
| app-api | `Chat.Ask` | web, Azure CLI (dev) | Federated credential: issuer `https://login.microsoftonline.com/<tenant>/v2.0`, subject = app-api managed identity, audience `api://AzureADTokenExchange` |
| energy-service | `Energy.Read` | app-api | |

- Identifier URIs are `api://<tenant-id>/<uniqueName>`; tokens are v2 (audience = app ID).
- Pre-authorization is the consent: no `requiredResourceAccess`, no admin consent, no prompt for the users of the tenant. The chain web → app-api → energy-service has no cycles, so one deployment creates everything.
- Owners: whoever runs `azd up` is added as an owner (needed to update the apps); owners are never removed automatically. When someone no longer operates the environment, remove them: `az ad app owner remove --id <app id> --owner-object-id <their object id>` for each app (list with `az ad app owner list --id <app id>`). CI never provisions, so it needs no Graph permission and no ownership.
- Outputs `WEB_APP_ID`, `APP_API_APP_ID`, `ENERGY_SERVICE_APP_ID`, `API_SCOPE`, `ENERGY_SERVICE_SCOPE` go to the container apps and the azd env.
- `azd down` does not delete them. Delete them with `az ad app delete --id <app id>` for each.

### Who can sign in
The apps are single tenant: members of the deployment tenant, and guests the tenant admin has invited (outside this app). Bicep sets `AUTH_TENANT_ID` and the web `ENTRA_AUTHORITY` from `tenant().tenantId`. A signed-in user sees "Your account isn't set up yet" until an operator maps them with `scripts/map_user.py --azure`. Details: [docs/auth-flow.md](../docs/auth-flow.md).

## Keeping deployed images on re-provision
This uses the azd **`exists` pattern**:
- Before every `azd provision`, azd looks up each service's container app by its `azd-service-name` tag. It then sets `SERVICE_WEB_RESOURCE_EXISTS`, `SERVICE_APP_API_RESOURCE_EXISTS` and `SERVICE_ENERGY_SERVICE_RESOURCE_EXISTS`.
- When a flag is `true`, `main.bicep` reads the running image from the existing app (`existing` resource) and passes it to the module. When it is `false` (first provision), the module uses the placeholder `mcr.microsoft.com/azuredocs/containerapps-helloworld:latest`.
- This needs no state in the azd `.env`, so it also works on fresh CI runners.

The placeholder listens on port 80, not on the app's target port. So on the very first provision, its revision fails its probes until `azd deploy` pushes the real image. This is expected.

## Postgres access
- Password auth is disabled. Only Entra tokens work.
- The deployer is the Entra admin (preflight fills `AZURE_PRINCIPAL_NAME`; azd fills `AZURE_PRINCIPAL_ID`).
- The managed identities' Postgres roles are **not** created by Bicep. The `postprovision` hook (`scripts/migrate.py --azure`, `scripts/seed.py --azure`, then `scripts/map_user.py --me --azure`) creates them as the Entra admin, and maps a signed-in deployer to the first demo customer (kept if already mapped). The seed is incremental: existing customers are skipped or topped up to yesterday, and user mappings are kept (`seed.py --azure --force` reloads all data and drops mappings). It uses these outputs:
  - `POSTGRES_HOST`, `POSTGRES_DATABASE`, `POSTGRES_ADMIN_USER`;
  - `ENERGY_SERVICE_IDENTITY_NAME` / `_CLIENT_ID`;
  - `APP_API_IDENTITY_NAME` / `_CLIENT_ID`.
- Firewall (POC):
  - `AllowAllAzureServicesAndResourcesWithinAzureIps` (0.0.0.0). This admits any Azure-hosted source, including Container Apps and GitHub-hosted runners.
  - `AllowDeployerClientIp` for the deployer's IP (`CLIENT_IP_ADDRESS`).
  - Later: private networking.

## Outputs (written to the azd env)
- `AZURE_RESOURCE_GROUP`
- `AZURE_CONTAINER_REGISTRY_ENDPOINT`, `AZURE_CONTAINER_REGISTRY_NAME`, `AZURE_CONTAINER_ENVIRONMENT_NAME`
- `AZURE_AI_PROJECT_ENDPOINT`, `AZURE_AI_ACCOUNT_NAME`, `AZURE_AI_PROJECT_NAME`, `AZURE_AI_MODEL_DEPLOYMENT_NAME`
- `APPLICATIONINSIGHTS_CONNECTION_STRING`, `APPLICATIONINSIGHTS_NAME`
- `APP_API_URL`, `ENERGY_SERVICE_URL` (internal)
- `POSTGRES_HOST`, `POSTGRES_DATABASE`, `POSTGRES_ADMIN_USER`
- `ENERGY_SERVICE_IDENTITY_NAME`, `ENERGY_SERVICE_IDENTITY_CLIENT_ID`
- `APP_API_IDENTITY_NAME`, `APP_API_IDENTITY_CLIENT_ID`, `APP_API_IDENTITY_PRINCIPAL_ID`
- `FRONTEND_URL`, `KEY_VAULT_NAME`
- `WEB_APP_ID`, `APP_API_APP_ID`, `ENERGY_SERVICE_APP_ID`, `API_SCOPE`, `ENERGY_SERVICE_SCOPE`
- `AZURE_LOCATION`, `AZURE_TENANT_ID`

## Typical flow (local)
```sh
azd auth login && az login
azd env new <env-name> && azd env set AZURE_LOCATION <region>
azd up
```
Hooks, in order:
1. `preprovision`: `scripts/preflight.py` (app-registration rights, model quota; sets `AZURE_PRINCIPAL_NAME`/`_TYPE`, `CLIENT_IP_ADDRESS`).
2. `postprovision`: `migrate.py`, `seed.py`, `map_user.py --me`.
3. `postdeploy`: `deploy_agent.py`, then `scripts/verify_deployment.py`:
   - no sign-in: web up, `/config.json` matches the app registrations, `/api/chat` without a token returns 401;
   - with a user token (yours from `az`, or `VERIFY_TOKEN`): `smoke.py` and `run_evals.py --mode auto`;
   - App Insights: the chat turn arrives as one trace with app-api, Foundry (`responsesapi`) and energy-service spans (without a token: the rejected request arrives).

Other people: `uv run python scripts/map_user.py --azure --tid <tid> --oid <oid> --customer-id <seeded customer id>`.
Browser E2E: `(cd frontend && E2E_BASE_URL="$(azd env get-value FRONTEND_URL)" E2E_TOKEN="$(az account get-access-token --scope "$(azd env get-value API_SCOPE)" --query accessToken -o tsv)" npm run test:e2e)`.

Deploy times (measured on dev) and faster paths:
| Change | Command | Time |
|---|---|---|
| Infra (Bicep) | `azd provision` (Postgres module ~4 min even when unchanged; seed skipped when data exists) | ~6 min |
| Code, all services | `uv run python scripts/deploy_parallel.py` (`azd deploy` per service, side by side) | ~2 min (sequential `azd deploy` ~4 min) |
| Code, one service | `azd deploy <service>` | 1.2–2.8 min |
| Agent definition | `uv run python scripts/deploy_agent.py` (skipped when unchanged; `--force` to create anyway) | ~2 s |
| App setting only | `az containerapp update -n <app> -g <rg> --set-env-vars K=V`, then `azd env set K V` so the next provision keeps it | ~20 s |

`azd deploy` builds and rolls out services one at a time. The postdeploy hook (`deploy_agent.py` + `verify_deployment.py`) runs on a full `azd deploy` / `azd up` and after `deploy_parallel.py`, not on `azd deploy <service>`.

Post-deploy checks (measured on dev): smoke 7–12 s, E2E 15–20 s, evals quick ~20 s / full ~5.5 min, telemetry visible in App Insights after ~8 s (p95 ~17 s).
- **Every deploy:** smoke, E2E, `run_evals.py` (auto mode). Auto runs the full eval only when files listed in `agent/eval.yaml` `policy.full_when_changed` (agent definition, golden set, app-api orchestration) changed since the last passing full run; otherwise only the `smoke`-tagged rows, deterministic checks, no Foundry judges.
- **Force a mode:** `--mode full` (before a release or nightly), `--mode quick`, `--mode local` (all rows, no judges).

Telemetry: App Insights receives requests, dependencies and GenAI spans from app-api, energy-service and Foundry (`cloud_RoleName == "responsesapi"`), joined by `operation_Id`. The Foundry portal's Tracing tab reads the same App Insights resource through the project connection. Probe calls (`/healthz`) are not traced, and every trace is kept (100 % fixed-percentage sampling; the distro default is a 5 spans/s rate limit that drops parts of chat turns). Override sampling with the standard `OTEL_TRACES_SAMPLER` / `OTEL_TRACES_SAMPLER_ARG` app settings; the untraced paths are `UNTRACED_PATHS` in `shared/.../telemetry.py`.
Images are built in ACR (`remoteBuild: true`), so the deploy machine needs no Docker or package-feed access.

## CI (`.github/workflows/azure-dev.yml`)
Split of work:
| Change | Who | How |
|---|---|---|
| Infra, app registrations, data (Bicep, `azure.yaml` hooks) | A person (or a coding agent with your `az login`) | `azd up` |
| Code and agent definition | GitHub Actions on push to `main` | `azd deploy` (postdeploy: agent version + verify) |

The workflow signs in with OIDC (no secrets), creates a fresh azd env, loads the outputs of the last `azd up` with `azd env refresh`, then runs `azd deploy`. It starts only after the CI workflow passes on a push to `main` (`workflow_run`), so failing code is never deployed. If `infra/` or `azure.yaml` changed since the last successful deploy, it fails before deploying (new code may need the new infra): run `azd up`, which provisions and deploys that code, then run the workflow once by hand (`gh workflow run azure-dev.yml`; manual runs skip the check) so it becomes the new baseline. It never provisions, so it needs no Graph permission, no app ownership, no Postgres access and no tenant admin.

One-time setup: `uv run python scripts/setup_ci.py` from a clone with a GitHub remote. The workflow file is named `azure-dev.yml` because that is the name `azd pipeline config` looks for; with any other name it offers to add its default workflow, which provisions. When azd asks to commit and push, answer **No**: the first run would fail before step 2 grants Azure AI User. It:
1. runs `azd pipeline config --auth-type federated --principal-role Contributor`: pipeline service principal `energy-usage-ci-<env>`, GitHub OIDC credential, Contributor on the subscription, repository variables `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_ENV_NAME`, `AZURE_LOCATION`;
2. sets `AZURE_PIPELINE_PRINCIPAL_ID` and runs `azd provision`, so Bicep gives the pipeline identity Azure AI User on Foundry (to publish the agent).

A service principal has no user, so CI verification covers endpoints, the 401 path and its telemetry; smoke and evals run only when a user token is supplied as `VERIFY_TOKEN`.

## Validate locally
```sh
az bicep build --file infra/main.bicep --stdout > /dev/null
az bicep lint  --file infra/main.bicep
```
