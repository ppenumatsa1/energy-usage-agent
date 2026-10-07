# Project Structure – energy-usage-agent (v0.3)

Location: repo root `energy-usage-agent/`. This is a monorepo with one `azd` project and three deployables plus one Foundry prompt agent.

**Decisions:**
- **Foundry prompt agent.** No Microsoft Agent Framework (MAF).
- Option B: the App API runs the tool calls.
- Option 2: one energy service with REST and MCP adapters over one core.
- uv workspace + `shared/`.
- Agent definition lives in the root `agent/` folder.

```text
energy-usage-agent/
├── README.md
├── AGENTS.md                         # agent guidance (read by all Copilot tools): rules, install/deploy, validation
├── azure.yaml                        # azd services: web, app-api, energy-service (+ agent deploy hook)
├── pyproject.toml, uv.lock           # uv workspace: shared, services/app-api, services/energy-service
├── compose.yaml                      # local Postgres (+ "full" profile for all services)
├── .env.example                      # synthetic local values only
├── .github/workflows/{ci.yml,azure-dev.yml}
├── tests/architecture/               # layer rules, no identity params, agent ↔ MCP sync, denylist scan
├── docs/
│   ├── functional-spec.md            # goal, scope, question types, errors, acceptance
│   ├── technical-spec.md             # components, identity flow, APIs, data model, NFR details
│   ├── project-structure.md          # this file + ownership rules
│   ├── architecture.md               # logical/process/physical views, diagrams, trust boundaries
│   ├── userflow.md                   # sign-in → ask → answer/table/chart, UI states, error UX
│   ├── business-rules.md             # customer scoping, date/tz rules, range limits, refusals
│   ├── issues-changes-fixes.md       # decision log, changes, incidents
│   └── plan.md                       # living implementation plan
├── agent/                            # Foundry PROMPT agent definition (deploy artifact, not runtime code)
│   ├── agent.yaml                    # name, model deployment, instructions ref, tools, response format
│   ├── instructions.md
│   ├── tools/                        # function tool specs mirrored from MCP tools/list (contract-tested)
│   ├── output-schema.json            # {answer, chart?, result_ids[]}
│   ├── eval.yaml                     # evaluation intent
│   ├── evals/datasets/               # golden questions + expected tool calls
│   └── .foundry/                     # agent metadata + eval caches (not runtime source)
├── shared/src/energy_usage_shared/
│   ├── auth/                         # Entra JWT validation (single tenant), Principal(tid, oid)
│   ├── contracts/                    # ToolResult, UsageSeries… (pydantic)
│   ├── problems.py                   # RFC 7807 helpers
│   └── telemetry.py                  # OpenTelemetry / App Insights
├── services/
│   ├── app-api/
│   │   ├── src/energy_usage_app_api/
│   │   │   ├── api/                  # create_app, dependencies, schemas, routers/{chat,conversations,me,health}
│   │   │   ├── application/          # ChatService, ports, models, errors, audit (framework-free)
│   │   │   ├── orchestration/        # Foundry SDK client, Option B function-tool loop
│   │   │   ├── infrastructure/       # mcp_gateway (MCP client), obo, conversations_pg, ratelimit
│   │   │   ├── projections/          # pure: tool outputs + agent output → answer/table/chart
│   │   │   ├── testing/              # fake agent, fake tool gateway, in-memory stores
│   │   │   └── config.py, bootstrap.py, main.py
│   │   ├── migrations/               # app schema (conversation ownership, stored turns)
│   │   ├── tests/{unit,integration}/     # integration: real energy-service over MCP
│   │   └── Dockerfile, pyproject.toml
│   └── energy-service/               # one core, two inbound adapters
│       ├── src/energy_usage_energy/
│       │   ├── api/                  # REST adapter: routers/{usage,meters,coverage,health}
│       │   ├── mcp/                  # FastMCP adapter mounted at /mcp: tools/{usage,compare,peaks,breakdown,meters,coverage}
│       │   ├── application/          # usage service, date ranges (tz), validation, customer resolution, ports
│       │   ├── infrastructure/       # postgres (MI token, SET LOCAL app.customer_id), queries
│       │   ├── testing/              # in-memory repository
│       │   └── config.py, bootstrap.py, main.py
│       ├── migrations/               # schema, RLS, roles, user→customer mapping
│       ├── tests/{unit,integration}/     # integration: cross-tenant RLS on real Postgres
│       └── Dockerfile, pyproject.toml
├── frontend/
│   ├── src/{auth,api,components,hooks,types}/  # MSAL, SSE client, Chat, ResultTable, ResultChart (Recharts)
│   ├── tests/{e2e,mocked}/
│   └── Dockerfile, nginx.conf.template, package.json, vite.config.ts
├── observability/{README.md,kql/}    # trace-completeness, authz-denials, tool-latency
├── scripts/                          # dev.py, local_db.py, migrate.py, seed.py, map_user.py, dev_token.py,
│                                     # sync_tool_specs.py, deploy_agent.py, deploy_parallel.py, smoke.py,
│                                     # run_evals.py, preflight.py, verify_deployment.py, setup_ci.py
└── infra/
    ├── main.bicep, main.parameters.json, README.md
    └── modules/                      # monitoring, registry, identity, postgres, foundry, aca-env, container-app
```

## Ownership rules
- `api/` and `mcp/` are transport adapters only. They call `application/`, never `infrastructure/` directly.
- `application/` imports no fastapi, mcp, azure, psycopg or openai.
- `orchestration/` is the only code that talks to Foundry. `agent/` holds no Python runtime code.
- `projections/` is pure: no async, no IO.
- `bootstrap.py` builds the runtime. `main.py` uses an app factory with no work at import time.
- Each service owns its migrations.

## Architecture contract tests
- The layer import rules above.
- **Security:** no REST route, MCP tool or `agent/tools` spec has a `customer_id`, `tenant_id`, `tid` or `oid` parameter.
- **Security:** every energy query goes through the RLS-scoped session helper.
- `agent/tools/*.json` must match the MCP `tools/list` schemas.
- The frontend only calls same-origin `/api`.

## Conventions
- Python 3.12, uv, ruff, pytest, pydantic-settings.
- React + Vite + TypeScript, eslint, vitest, Playwright, Recharts.
- Config through environment variables; azd outputs feed app settings. Secrets are never committed.
- **No customer information, ever.** This applies to code, docs, comments, seed data, tests, evals, commit messages and config:
  - No customer or company names, people's names, emails, or meeting/email notes.
  - No tenant, subscription or resource IDs, and no real usage data.
  - Use generic terms ("customer", "operator", "tenant A/B") and synthetic data only.
  - Environment-specific values come from azd environments, which are not committed.
  - CI runs a check against a denylist that is kept outside the repo (a CI secret), so the denylist itself never lands in the repo.
