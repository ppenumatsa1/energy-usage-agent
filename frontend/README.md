# Energy Usage Assistant – frontend

Single-page app (Vite + React 18 + TypeScript) where signed-in users ask natural-language questions about their energy usage and get an answer, a table and a chart.

- Auth: `@azure/msal-browser` / `@azure/msal-react` (Entra ID, single tenant) or a local **dev** sign-in.
- Charts: `recharts`.
- Calls only same-origin `/api/...` URLs with `Authorization: Bearer <token>`.

## Local development

```bash
npm install
npm run dev      # http://localhost:5173, proxies /api -> http://localhost:8000
npm run lint
npm test         # vitest + Testing Library (tests/mocked)
npm run build    # tsc -b && vite build -> dist/
```

End-to-end tests (Playwright, `tests/e2e/`). Browsers are not installed by default:

```bash
npx playwright install chromium
npm run test:e2e   # local: starts `npm run dev` unless E2E_BASE_URL is set

# Deployed environment: real Entra redirect check + a signed-in journey with a real user token
E2E_BASE_URL=https://<web> E2E_TOKEN="$(az account get-access-token --scope "$(azd env get-value API_SCOPE)" --query accessToken -o tsv)" npm run test:e2e
```
MFA sign-in can't be scripted, so the journey test serves a dev-mode `config.json` and hands the UI the real token; every request after sign-in goes to the real deployed services.

## Runtime config

The app fetches `/config.json` at startup; nothing is baked in at build time.

```json
{ "authMode": "entra" | "dev", "clientId": "", "authority": "", "apiScope": "" }
```

- `public/config.json` is the local default (`authMode: "dev"`).
- **dev**: no MSAL. The app lists synthetic users from `GET /api/dev/users` and exchanges the chosen one for a token via `POST /api/dev/token` (kept in `sessionStorage`).
- **entra**: MSAL redirect sign-in against `authority` (the home tenant, `https://login.microsoftonline.com/<tenant>`), then `acquireTokenSilent` for `[apiScope]`, falling back to a redirect. `clientId`, `authority` and `apiScope` are required.

## Container

```bash
docker build -t energy-usage-frontend .
docker run -p 8080:8080 \
  -e APP_API_URL=https://app-api.example.com \
  -e AUTH_MODE=entra \
  -e ENTRA_CLIENT_ID=<spa-client-id> \
  -e API_SCOPE=api://<api-client-id>/<scope> \
  energy-usage-frontend
```

`nginxinc/nginx-unprivileged` on port **8080**:

- serves the SPA with history fallback and basic security headers (CSP, `X-Content-Type-Options`, `Referrer-Policy`);
- proxies `/api/` to `APP_API_URL` (prefix kept, SNI on, buffering off for SSE, 120 s read timeout);
- writes `/config.json` at start (`docker/40-config-json.sh`).

| Env var | Default | Purpose |
|---|---|---|
| `APP_API_URL` | `http://localhost:8000` | App API origin (scheme + host[:port], no path or trailing slash) |
| `AUTH_MODE` | `entra` | `entra` or `dev` |
| `ENTRA_CLIENT_ID` | _(empty)_ | SPA app registration client ID |
| `ENTRA_AUTHORITY` | — (required for entra) | MSAL authority: `https://login.microsoftonline.com/<tenant>` |
| `API_SCOPE` | _(empty)_ | Scope requested for the App API token |

## Layout

```
src/
  api/         fetch client, SSE parser, problem+json mapping, config loader
  auth/        Entra + dev auth providers, sign-in screens
  components/  workspace, answer card, table, chart, composer
  hooks/       useApi, useMe, useChat, useConversations
  types/       API and config types
tests/mocked/  vitest tests (mocked fetch)
tests/e2e/     Playwright smoke + deployed-app E2E
```
