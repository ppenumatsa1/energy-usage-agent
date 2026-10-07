# Technical Spec – energy-usage-agent (v0.3)

> Status: Draft for review. **[OPEN]** and **[SPIKE]** mark items that need a decision or verification.
> Runtime view and identity flow: [architecture.md](architecture.md). Rules: [business-rules.md](business-rules.md). Layout: [project-structure.md](project-structure.md).

## 1. Technology choices
| Area | Choice |
|---|---|
| Frontend | React (Vite + TypeScript), MSAL.js, Recharts |
| App API | FastAPI (Python 3.12) |
| Agent | Azure AI Foundry **prompt agent**, called with the Foundry SDK (`azure-ai-projects`, Responses + conversations). **No Microsoft Agent Framework.** |
| Tool protocol | MCP over streamable HTTP |
| Energy service | FastAPI with a REST adapter (`/v1`) and a FastMCP adapter (`/mcp`) over one application core |
| Database | Azure Database for PostgreSQL Flexible Server |
| Authentication | Microsoft Entra ID, single tenant (external users are B2B guests); see [auth-flow](auth-flow.md) |
| Hosting | Azure Container Apps (3 apps) + Azure AI Foundry |
| Observability | Application Insights + Log Analytics (OpenTelemetry) |
| Packaging | uv workspace (`shared/`, `services/app-api`, `services/energy-service`) |
| IaC / CI/CD | Bicep · GitHub Actions + `azd` |

## 2. Component responsibilities
| Component | Does | Does NOT |
|---|---|---|
| frontend | Sign-in, chat UI, renders answer/table/chart, keeps `conversationId`, calls same-origin `/api` only | Hold secrets; call the energy-service |
| app-api | JWT validation, onboarding check (via energy-service `/v1/me`, cached), rate limit, OBO, Foundry tool loop (`orchestration/`), MCP client, projections, conversation ownership | Query the DB; let the LLM produce table numbers |
| agent (`agent/`) | Instructions, tool specs, output schema, evals. Deployed as a Foundry prompt agent | Contain runtime code; see user tokens or customer IDs |
| energy-service | Token validation, **sole owner of the `(tid, oid)` → customer mapping**, input validation, date resolution, scoped SQL, audit events | Accept a customer ID from any input |
| Postgres | Storage; RLS by `customer_id` | Be reachable without Entra auth |

## 3. App registrations (single tenant)
Created by `infra/modules/entra.bicep` on every `azd provision`; names are `energy-usage-<role>-<token>` (unique per environment).
| App | Type | Exposes / requests |
|---|---|---|
| web | SPA | Requests `Chat.Ask` |
| app-api | Web API (confidential, federated credential via managed identity) | Exposes `Chat.Ask`; requests `Energy.Read` (OBO) |
| energy-service | Web API | Exposes `Energy.Read`. One audience for both `/v1` and `/mcp` |

- Only accounts in the home tenant sign in: members, and guests the tenant admin has invited. Pre-authorization means no consent prompts. Services accept tokens only from `AUTH_TENANT_ID` and only from the clients in `AUTH_ALLOWED_CLIENT_IDS` (token `azp`): app-api accepts the web app, plus the Azure CLI when `ENTRA_PREAUTHORIZE_AZURE_CLI` is `true` (scripts test as you); energy-service accepts app-api only.
- Signing in is not access: data needs a `(tid, oid)` → customer mapping (BR-2) and Postgres RLS.
- Token flow, settings and failure screens: [auth-flow](auth-flow.md).

## 4. MCP tools (energy-service `/mcp`)
None of the tools take a customer identifier ([BR-1](business-rules.md#customer-scoping-and-onboarding)). All inputs are validated against [BR-7](business-rules.md#range-and-granularity-limits).
| Tool | Params | Returns |
|---|---|---|
| `get_usage` | `start`, `end`, `granularity` (hour/day/month), `site_id?`, `meter_id?` | series `{period, kwh}` + total |
| `compare_usage` | `period_a{start,end}`, `period_b{start,end}`, `granularity` | totals, delta, pct_change, aligned series |
| `get_peak_usage` | `start`, `end`, `granularity`, `top_n` (≤10), `order` (max/min) | ranked periods |
| `get_usage_breakdown` | `start`, `end`, `group_by` (site/meter), `granularity` | per-group totals + series |
| `list_sites_and_meters` | — | the customer's sites and meters |
| `get_data_coverage` | `start`, `end` | available range, missing periods |

Every result includes `result_id`, `columns`, `rows`, `unit`, `tz`, `assumptions`, `summary` and an optional `chart_hint`.
- `start`/`end` accept `YYYY-MM-DD`, `YYYY-MM` or a keyword (`today`, `yesterday`, `this_week`, `last_week`, `this_month`, `last_month`, `this_year`, `last_year`, `last_7_days`, `last_30_days`, `last_90_days`, `last_12_months`). The server resolves keywords in the customer's time zone ([BR-4](business-rules.md#time-and-date-resolution)). Rolling windows (`last_N_days`) include today.
- A `site_id`/`meter_id` that is unknown or belongs to another customer is rejected as `invalid_argument`.
- Breakdown groups are labelled `"<name> (<id>)"`, so two meters with the same name stay separate.
- Tool errors are a JSON `{code, message}` in the MCP error text.

## 5. REST API (energy-service `/v1`)
Same application core as MCP.
- `GET /v1/usage?start&end&granularity&site_id&meter_id`
- `GET /v1/usage/compare?a_start&a_end&b_start&b_end&granularity`
- `GET /v1/usage/peaks?start&end&granularity&top_n&order`
- `GET /v1/usage/breakdown?start&end&group_by&granularity`
- `GET /v1/sites`
- `GET /v1/me`: onboarding status for the caller (no customer details beyond display name)
- `GET /v1/coverage?start&end`
- `GET /healthz`, `GET /readyz`

Errors use RFC 7807 problem+json: `400 invalid_range`, `401`, `403 not_onboarded`, `404 no_data`, `422`.

## 6. Agent (Foundry prompt agent)
Defined in `agent/`:
- `agent.yaml`: model, tools and response format
- `instructions.md`
- `tools/*.json`: function tool specs, synced from MCP `tools/list` and checked by a contract test
- `output-schema.json`
- `eval.yaml` + `evals/`
- `.foundry/`

Instructions summary:
- Answer energy-usage questions only.
- Always use tools for numbers.
- State assumptions.
- Ask a clarifying question when ambiguous.
- Ignore requests for other customers' data.

Output (strict JSON schema response format): `{ answer, status: ok|no_data|clarify|refused, chart: {type, x, y, series, title} | null, result_ids: [] }`.

- Function tools use `strict: false`, because the tool schemas have optional parameters.
- No temperature: the default model is a reasoning model.
- Model: `gpt-5.6-luna`, GlobalStandard, by default (`AZURE_AI_MODEL_NAME`, `_VERSION`, `_SKU`, `_CAPACITY`); the deployment name comes from the azd env.

Deployment: the `azd` postdeploy hook runs `scripts/deploy_agent.py`, which creates a new agent version from `agent/` (`--dry-run` prints it).

## 7. App API
### Endpoints
- `POST /api/chat` with `{message (1–2000 chars), conversationId?}`.
  - JSON response: `{answer, status, table, chart, assumptions, conversationId, correlationId, createdAt, trace}`. `status` adds `error` (loop limit reached) to the agent's statuses. `table` and `chart` are present only when `status` is `ok`.
  - `trace` ("How this was answered"): `{agent (fake|foundry), agentName, durationMs, steps[{tool, arguments, status (ok|error), rows, errorCode, errorMessage, durationMs, resultId, assumptions, summary}], checks[{name, detail, outcome (pass|info|blocked)}], resultIds}`. Steps hold tool names, arguments, counts and tool metadata only; rows stay in `table`. `resultIds` are the results the agent cited.
  - With `Accept: text/event-stream`: events `status` (`{stage: thinking|tool|composing, tool?}`), then one `result` (same body as JSON) or `error` (problem body).
- `GET /api/conversations`: `[{conversationId, title, createdAt, updatedAt, turnCount}]`, newest activity first.
- `GET /api/conversations/{id}`: `{conversationId, title, createdAt, updatedAt, turns[{question, response}]}`, where `response` is the stored `ChatResponse` exactly as shown. 404 `conversation_not_found` if missing, expired or not yours.
- `DELETE /api/conversations/{id}` (204): removes the record, its turns and the Foundry conversation (best effort).
- `GET /api/me`: `{onboarded, customerName, timezone, userName}`
- `GET /api/status` (signed in, onboarding not required): `{components[{id (api|energy|database|agent), label, status (ok|down), detail}], historyRetentionDays}` for the header status pills. Energy readiness comes from the energy-service `/readyz`; the agent is `down` when app-api can't read the Foundry agent definition (5 s limit, result cached 60 s).
- `GET /healthz`
- Dev only (`AUTH_MODE=dev`, never in Azure): `GET /api/dev/users`, `POST /api/dev/token {user}`.

Errors are problem+json with a `code`: `401 unauthorized` (missing or invalid token; the UI signs in again), `403 not_onboarded`, `404 conversation_not_found`, `422 invalid_request`, `429 rate_limited` (with `Retry-After`), `503 upstream_unavailable`. Errors found before streaming starts keep their HTTP status even for SSE requests.

Error handling:
- Every error body and the `X-Correlation-Id` header carry the correlation ID; unexpected 500s return `internal_error` with it. The web app shows it (copyable) next to the message.
- History database down: `503 upstream_unavailable`. A turn whose answer was produced but couldn't be saved is still returned (`history_save_failed` logged).
- energy-service: database unreachable or a query over `DB_STATEMENT_TIMEOUT_MS` (10 s) gives `503 upstream_unavailable` with `Retry-After: 5`; over MCP the tool returns `internal` with a try-again message. `/readyz` returns 503 when the database ping (3 s) fails.
- Timeouts: Postgres connect `DB_CONNECT_TIMEOUT_SECONDS` (10) and pool wait `DB_POOL_TIMEOUT_SECONDS` (10) in both services (pooled connections are checked at checkout, so a Postgres restart doesn't fail requests); Foundry 120 s (10 s connect; SDK retries conversation calls, `responses.create` retried only on 429 or connection failure); MCP request 60 s; OBO 10 s (one retry); Graph profile 10 s (3 attempts).
- SSE: a client disconnect cancels the turn (`chat_cancelled`), with no error event. The web app never resends a message by itself: a stream that breaks after it started shows `stream_interrupted` and reloads the conversation from History; "Try again" is a click and is hidden where resending can't help. Offline failures show `network_error`. A React error boundary catches render errors.

Rate limit: 20 requests/min per `tid:oid` (`RATE_LIMIT_PER_MINUTE`), in memory per replica.

### Orchestration loop (`orchestration/`)
1. Create or continue the Foundry conversation.
2. Send the user message.
3. While the response has `function_call` items and the loop limit (5) is not reached:
   - Validate the tool name against the allow-list.
   - Call MCP `tools/call` with the OBO token.
   - Capture the output.
   - Submit a trimmed `function_call_output` (at most 100 rows; the user still sees all rows) on the same conversation with `agent_reference`.
4. Parse the final structured output.
5. Projections build the table and chart from the captured outputs.

Failure handling: an Azure OpenAI `content_filter` rejection (e.g. a jailbreak attempt) becomes a `refused` answer; other agent errors become `503 upstream_unavailable`. On any early exit (loop limit, MCP failure, submit failure, blocked output, cancellation) the open `function_call` items are closed with an `aborted` error output through `conversations.items.create` (does not run the model; 5 s, shielded from cancellation): Foundry rejects any new message while a call has no output. If an existing conversation still answers `400 No tool output found`, the turn starts a new Foundry conversation and retries once (`agent_conversation_reset`; earlier model context is lost, stored history is kept). An MCP result that doesn't parse becomes tool error `internal` (`mcp_result_invalid`). The loop limit error is raised only when the last response still asks for tools. Errors raised inside the MCP client's task group are unwrapped so they keep their status. GenAI tracing (`AIProjectInstrumentor`) is best effort and never breaks a turn.

Conversation state: a Foundry conversation per chat holds the model context. The App API stores `conversationId → (tid, oid)` ([BR-11](business-rules.md#conversations-and-usage)) and every turn as shown to the user ([BR-14](business-rules.md#conversations-and-usage)), so a reopened conversation renders the same text, table, chart and trace. Tool calls are timed by a wrapper around the per-turn gateway, so the trace is the same for the fake and the Foundry agent.

## 8. Data model (Postgres)
```sql
customers(customer_id uuid PK, name, timezone text /* IANA */, created_at)
user_customer(tid uuid, oid uuid, customer_id FK, role, PK(tid,oid))
sites(site_id PK, customer_id FK, name, city)
meters(meter_id PK, customer_id FK, site_id FK, name, type)
usage_readings(customer_id, meter_id, ts timestamptz, kwh numeric, PK(meter_id, ts))  -- 15-min intervals
usage_daily(customer_id, site_id, meter_id, day date /* customer tz */, kwh)          -- rollup
```
App API schema `app_api` (separate role `app_api_rw`, no access to `energy`):
```sql
conversations(conversation_id uuid PK, tid uuid, oid uuid, agent_conversation_id, title, created_at, updated_at)
turns(turn_id bigserial PK, conversation_id FK ON DELETE CASCADE, question text, response jsonb, created_at)
```
- Every conversation query filters by `(tid, oid)`; turns are read only after that ownership check.
- Retention: conversations idle longer than `HISTORY_RETENTION_DAYS` (30) are hidden from the list and return 404 on open and chat. A background job in app-api deletes them with their turns and Foundry conversations: first about 60 s after start, then every `HISTORY_PURGE_INTERVAL_MINUTES` (60; `0` turns it off), `HISTORY_PURGE_BATCH_SIZE` (200) per run, `FOR UPDATE SKIP LOCKED` so replicas don't collide.

- RLS is ON for `sites`, `meters`, `usage_readings` and `usage_daily`, with policy `customer_id = current_setting('app.customer_id')::uuid`.
- The energy-service DB role is SELECT only and not the table owner (it cannot bypass RLS). It only reads `user_customer` through a narrow lookup.
- Seed: 3 customers across 2 tenants, 1–3 sites and meters each, 13 months of 15-minute data, seasonal and weekday patterns, deliberate gaps.

## 9. Hosting and networking (POC)
- Container Apps:
  - `web` is the only external app. Its nginx proxies same-origin `/api` to app-api.
  - `app-api` and `energy-service` are **internal**, and both still require a JWT.
- Postgres: Entra-only auth; firewall allows Azure services (Container Apps have no fixed outbound IP without a VNet) plus the deployer's IP for migrations and seed. Private networking replaces both later.
- No secrets: Postgres, Foundry, ACR and App Insights use managed identities, OBO uses a federated credential, CI uses OIDC. So there is no Key Vault; add one only when something can't use a managed identity or federated credential.
- Later: private networking ([architecture: physical view](architecture.md#4-physical-view)).

## 10. CI/CD
- GitHub Actions with OIDC + `azd`.
- PR checks (`.github/workflows/ci.yml`):
  - ruff lint + format, mypy, eslint
  - pytest (including RLS tests on a Postgres service container and architecture contract tests), vitest, frontend build
  - Bicep build + lint
  - customer-information scan against the `CUSTOMER_DENYLIST` secret
  - Later: agent evals (smoke set), Bicep what-if
- Main branch (`.github/workflows/azure-dev.yml`): `azd deploy` to dev (code + agent version + verify). Runs only after CI passes on `main`. Infra is applied by a person with `azd up`; infra changes since the last deploy stop it. Prod **[OPEN]**.

## 11. Testing
- **Unit:** date resolution, validation, SQL builders, projections.
- **Contract:**
  - layer import rules;
  - no customer identifiers in routes, tools or agent tool specs;
  - `agent/tools` ↔ MCP `tools/list`;
  - REST ↔ MCP parity.
- **Security:** cross-tenant negative tests at the REST, MCP and prompt levels; RLS tests against real Postgres.
- **Agent evals** (`scripts/run_evals.py`, `--mode auto` by default): full (all rows + judges, ~5.5 min) only when agent-shaping files (`agent/eval.yaml` `policy.full_when_changed`) changed since the last passing full run; otherwise quick (`smoke`-tagged rows, deterministic only, ~20 s). The golden set runs through the deployed app as a signed-in user. Deterministic checks (status, expected tools, rows; gate 80%), then a Foundry evaluation with built-in judges (intent resolution, task adherence, tool call accuracy, relevance). Judges get the agent transcript: system prompt, tool calls with results, and the final JSON output.
- **Smoke** (`scripts/smoke.py`): `/api/me`, `/api/status`, chat JSON + SSE, conversation list + history.
- **E2E** (Playwright, `frontend/tests/e2e/`): the real Entra redirect (client ID + scope), and a signed-in journey on the deployed app: ask → answer, table, chart, trace → history → refusal → delete.

## 12. Spikes / risks
1. **[SPIKE – done in the dev tenant]** OBO (app-api → energy-service) works in Azure. Admin consent in other tenants is still to be tried.
2. **[SPIKE – done]** Prompt agent with function tools + JSON-schema output on `gpt-5.6-luna`; `function_call_output` through Responses/conversations works in Azure.
3. **[RISK]** Streaming (SSE) when the tool loop sits in between: stream only the final answer text.
