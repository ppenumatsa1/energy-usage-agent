# Auth and token exchange

How a person signs in, how their identity travels to the data, and which token is used at each step.

## In short
- **Single tenant.** All three app registrations live in the home tenant (`AzureADMyOrg`). Only accounts in that tenant can sign in: members, and guests that the tenant admin has already invited and who accepted. Inviting people is not part of this app.
- **Signing in is not access.** Data needs a `(tid, oid)` → customer mapping ([BR-2](business-rules.md#customer-scoping-and-onboarding)) and Postgres RLS.
- **The user's identity reaches the data; the user's token never reaches Foundry.** app-api swaps the user's token for an energy-service token (on-behalf-of, OBO) and runs the tools itself.
- **No secrets, no consent prompts.** app-api authenticates to Entra with its managed identity (federated credential). Pre-authorization covers both custom scopes.

## Flow
1. **Sign-in.** The browser (MSAL, authority `https://login.microsoftonline.com/<home tenant>`) asks for `api://<app-api>/Chat.Ask`. A guest signs in with their own organization's password and MFA; Entra still issues a home-tenant token.
   → **Token A**: audience app-api, scope `Chat.Ask`, `tid` = home tenant, `oid` = the user's object in the home tenant (for a guest, the guest object, not their account in their own organization).
2. **Call the API.** The browser sends Token A to same-origin `/api`. The web app's nginx proxies it to the internal app-api.
3. **app-api validates Token A**: signature (home tenant keys), issuer = home tenant, audience, `tid` = `AUTH_TENANT_ID`, scope `Chat.Ask`, and that it is a user token (app-only tokens are rejected).
4. **Token exchange (OBO).** app-api asks Entra for `api://<energy-service>/Energy.Read` on behalf of the user. It sends Token A as the assertion and proves its own identity with a managed-identity token (`api://AzureADTokenExchange`) instead of a secret.
   → **Token B**: audience energy-service, scope `Energy.Read`, same `tid` and `oid`. Cached per user until 2 minutes before expiry.
5. **Agent.** app-api calls Foundry with its **managed identity**. Foundry gets the message and trimmed tool results, never a user token or a customer ID.
6. **Tools.** When the agent asks for a tool, app-api calls energy-service (`/mcp`, and `/v1/me` for the profile) with Token B. energy-service validates it like step 3 (scope `Energy.Read`).
7. **Data.** energy-service maps `(tid, oid)` to a customer, sets the RLS customer for the transaction and queries Postgres with its **managed identity** (SELECT-only role; RLS applies).

## Tokens and credentials
| Hop | Credential | Audience / scope | Checked by |
|---|---|---|---|
| Browser → app-api | Token A (user) | app-api / `Chat.Ask` | app-api |
| app-api → Entra (OBO) | Token A + app-api managed identity (federated credential) | — | Entra |
| app-api → energy-service | Token B (user, via OBO) | energy-service / `Energy.Read` | energy-service |
| app-api → Foundry | app-api managed identity | Azure AI | Foundry |
| energy-service → Postgres | energy-service managed identity | Postgres (Entra auth) | Postgres + RLS |

## App registrations
| App | Exposes | Pre-authorized clients | Other |
|---|---|---|---|
| `energy-usage-web-<token>` (SPA) | — | — | Redirect URIs: the web URL, `http://localhost:5173` |
| `energy-usage-app-api-<token>` (web API) | `Chat.Ask` | web (+ Azure CLI in dev, for test scripts) | Federated credential = app-api managed identity |
| `energy-usage-energy-service-<token>` (web API) | `Energy.Read` | app-api | — |

- `infra/modules/entra.bicep` creates and updates all three on every `azd provision` (Microsoft Graph Bicep extension).
- Pre-authorization is the consent: no `requiredResourceAccess`, no admin consent, no prompts. Scopes are `api://<home tenant>/<app uniqueName>/<scope>`.

## Giving a person access
1. The tenant admin invites the person as a guest (outside this app), and they accept.
2. An operator looks up their object ID in the home tenant (for example `az ad user list --filter "mail eq '<email>'" --query "[0].id"`) and maps it: `uv run python scripts/map_user.py --azure --tid <home tenant> --oid <object id> --customer-id <customer>`.
3. The person signs in.

## What users see when something is wrong
| User sees | Cause | Where to look |
|---|---|---|
| Entra error page (for example AADSTS50020) | Account isn't in the home tenant (not invited, or invite not accepted) | Entra sign-in logs |
| "Your account isn't set up yet" | No `(tid, oid)` mapping | `map_user.py` |
| "Your session has expired. Signing you in again…" | 401: missing, expired or invalid token | App Insights `authz_denied` (reason) |
| "Service temporarily unavailable" | 503: token exchange failed or energy-service is down | App Insights `obo_failed` (`error`, `error_codes`) |

## Settings
| Setting | Service | Value (Bicep) |
|---|---|---|
| `ENTRA_AUTHORITY` | web | `https://login.microsoftonline.com/<home tenant>` |
| `ENTRA_CLIENT_ID`, `API_SCOPE` | web | web app ID, `api://<home tenant>/<app-api>/Chat.Ask` |
| `AUTH_TENANT_ID` | app-api, energy-service | home tenant (`tenant().tenantId`) |
| `AUTH_AUDIENCE`, `AUTH_REQUIRED_SCOPE` | app-api, energy-service | own app ID; `Chat.Ask` / `Energy.Read` |
| `ENTRA_CLIENT_ID`, `ENERGY_SERVICE_SCOPE`, `AZURE_CLIENT_ID` | app-api | app-api app ID, `api://<home tenant>/<energy-service>/Energy.Read`, managed identity client ID |

Tenant and app IDs live only in the azd env and Azure, never in the repo.

**Local:** `AUTH_MODE=dev` replaces Entra with HS256 dev tokens and a dev OBO that mints Token B directly. Settings refuse dev auth when `ENVIRONMENT=azure`.

## Why single tenant + guests
| Option | Result |
|---|---|
| Multi-tenant apps (tried first) | Each organization must consent to all three apps in its own tenant. Many block user consent, so an admin has to approve; the token exchange failed for users whose organization hadn't. |
| app-api calls energy-service with its own identity (no OBO) | Fewer approvals, but energy-service would trust app-api for the user's identity instead of checking a user token. |
| **Single tenant + guests (chosen)** | No consent outside the home tenant; the tenant admin decides who is in; the OBO chain is unchanged. Each person needs a guest invitation. |
