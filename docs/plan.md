> Repo mirror of the living plan. Update both together.

# energy-usage-agent – Plan (living document)

_Last updated: 2026-10-06 — v0.5 (deployed to Azure dev)_

## Context
- Goal: authenticated users ask natural-language questions about their energy usage and get text + table + chart.
- Project folder: `energy-usage-agent/`. Docs live in `docs/` and are the source of truth.

## Approach
Specs first, then structure, then build. Implementation approved and started on 2026-10-06.

| Phase | Artifact | Status |
|---|---|---|
| 1. Functional spec | `docs/functional-spec.md`, `userflow.md`, `business-rules.md` | Draft v0.3 |
| 2. Technical spec | `docs/technical-spec.md`, `architecture.md` | v0.4 (updated to the build) |
| 3. Project structure | `docs/project-structure.md` | Agreed v0.3 |
| 4. Local build (no Azure) | all services, agent definition, infra, CI | **Done**: runs end to end locally |
| 5. Azure deployment + spikes | `azd up`, real agent, OBO | **Done**: deployed to dev; smoke, E2E, evals, tracing verified |
| 6. Evals + hardening | Foundry evals, Playwright E2E, mypy in CI | Evals + E2E done (run by hand), mypy in CI; CI deploy wiring pending |

## Build status
| Component | State | Verified by |
|---|---|---|
| energy-service (REST + MCP, Postgres RLS) | Done | unit, API, MCP and RLS tests on real Postgres |
| app-api (chat JSON/SSE, OBO, Foundry loop, projections, conversations + stored history, trace, status) | Done | unit + API tests; full-stack test through real MCP; local smoke |
| web (React, MSAL + dev sign-in, table/chart) | Done | eslint, vitest, build; local proxy smoke |
| agent/ (instructions, tools, output schema, golden set) | Done (agent v3 in Foundry) | contract tests; golden set 14/14 deterministic, Foundry judges ≥ 10/14 except tool call accuracy 7/10 |
| Azure dev environment | Deployed | `azd up` end to end with no manual steps; verify 6/6 (endpoints, smoke, evals, App Insights trace); Playwright E2E 3/3; guest sign-in; probes not traced |
| infra (Bicep incl. Entra app registrations, azd hooks) + CI/CD | Deployed (dev) | `azd provision`/`azd deploy` with all hooks; CI deploy path (fresh env + `azd env refresh` + `azd deploy`) simulated locally; workflow + `setup_ci.py` not yet run in GitHub |
| Scripts (local DB, migrate, seed, map user, dev token, dev, smoke, sync, deploy agent, evals, preflight, verify, CI setup) | Done | used in the local run and the Azure deployment |

## Decisions (summary; detail in `docs/issues-changes-fixes.md`)
- **No customer information in the project, now or in the future.** No customer or company names, people, emails, meeting notes, tenant/subscription IDs or real data. Use generic terms ("the customer", "operator") and synthetic seed data only.
- Stack:
  - React + MSAL + Recharts
  - FastAPI app-api
  - Foundry **prompt agent** via the SDK (no Microsoft Agent Framework)
  - energy-service (FastAPI REST `/v1` + FastMCP `/mcp`, one core)
  - Postgres with RLS
  - Entra single tenant + B2B guests
  - Container Apps
  - App Insights
  - Bicep + azd + GitHub Actions
- Sign-in: single tenant; people from other organizations are guests the tenant admin invited (outside the app). Data access only via the `(tid, oid)` → customer mapping + RLS. Flow: `docs/auth-flow.md`.
- Cutovers, not fallbacks: replaced code and settings are removed, not kept alongside.
- No manual install steps: `azd up` (preflight, Bicep incl. app registrations, data + self-mapping, deploy, verify). CI/CD Option B: CI (`azure-dev.yml`) deploys code + agent with OIDC (`setup_ci.py`, no admin); infra changes are applied by a person with `azd up`, CI deploys only after the CI workflow passes, and infra changes since the last deploy stop it.
- Evals: `run_evals.py --mode auto` runs the full eval (judges) only when the agent changed; otherwise a quick deterministic subset.
- Deploys: incremental seed (no re-seed on provision), agent version only when its definition changes, `scripts/deploy_parallel.py` for multi-service code deploys.
- Identity Option B: the App API runs the tool loop with a user OBO token; Foundry never sees user tokens.
- Customer comes from `(tid, oid)` mapping only; no customer identifiers in any tool or route.
- Table and chart numbers come from captured tool outputs (projections), never the LLM.
- Layout: root `agent/`; uv workspace + `shared/`; 3 deployables (frontend, app-api, energy-service).
- POC networking: only the web app is public; app-api (behind the web `/api` proxy) and energy-service are internal and still require a JWT.

## Open items
1. ~~Model and region~~: `gpt-5.6-luna`, GlobalStandard, eastus2.
2. Rate limit value (assumed 20 requests/min/user).
3. Latency targets.
4. Prod environment.
5. ~~App registration names~~: `energy-usage-<role>-<token>`, created by Bicep.
6. Week start; month-to-date comparison semantics; 15-min granularity exposure.
7. ~~Relative-date keywords vs explicit dates~~: keywords, resolved on the server.
8. ~~Conversation list in the POC UI~~: done, with stored history (30 days, BR-14).
9. Admin mapping by script (`scripts/map_user.py`).
10. ~~app-api ingress~~: internal behind the web app's `/api` proxy.

## Spikes
1. ~~OBO in Azure~~: works in the home tenant (members and guests).
2. ~~Prompt agent function tools + JSON-schema output~~: works in Azure.

## Next steps
1. CI: pushed to GitHub (CI workflow green; Deploy skipped until set up); run `scripts/setup_ci.py`, first deploy run; decide how CI gets a user token for smoke/evals (`VERIFY_TOKEN`); add the `CUSTOMER_DENYLIST` secret.
2. Prove the from-scratch install in a fresh environment by following `AGENTS.md` (`azd env new` + `azd up --no-prompt`), then `azd down --purge`; automate app-registration cleanup (a `postdown` hook) so teardown has no manual step.
3. Evals: add custom judges that understand refusals/clarifications (built-in judges reward fulfilling any request); grow the golden set from production traces.
4. Remove the tracing workaround when azure-ai-projects checks `is_recording()` itself.
5. Hardening: rate limit store for >1 replica, private networking (below). (Review fixes P0–P2, error handling, Key Vault removal done 2026-10-07.)

## Notes
- Private networking later: Foundry private networking + a dedicated MCP subnet (foundry-samples `19-private-network-agent-tools`).
