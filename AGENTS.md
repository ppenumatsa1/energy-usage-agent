# Guidance for coding agents

Read `README.md`, then `docs/architecture.md` and `docs/business-rules.md` (the single source for rules).

## Hard rules
- **No customer information, ever**: no customer names, people, tenant/subscription IDs, real data or real endpoints in any file, test, sample or commit. Use the synthetic data and demo users only. CI scans with a secret denylist.
- **Customer comes from identity only** (BR-1). Never add `customer_id`, `tenant_id`, `tid`, `oid` or similar to a REST route, MCP tool or agent tool. `tests/architecture` enforces this.
- **Energy SQL runs only inside `rls_session()`** (`energy-service/.../infrastructure/postgres.py`). Do not add other ways to query customer data.
- **Numbers come from tools** (BR-8). The table and chart are built from tool results in `app-api/.../projections/`, never from model text.
- Prompt instructions are not a security control.
- **Cutovers, not fallbacks**: when you replace code, settings or scripts, delete the old ones. No compatibility shims or "legacy" paths.
- **The app never invites or manages guests.** People from other organizations are guests the tenant admin already invited; the app only signs them in ([docs/auth-flow.md](docs/auth-flow.md)).
- **No manual install steps.** Anything a new environment needs goes into Bicep or an azd hook script, not into a "do this by hand" doc step.

## Bootstrap
**Tools**: Python 3.12, uv, Node 22, Azure CLI, azd. No Docker (images build in Azure Container Registry). Check with `uv --version && node --version && az version && azd version`.

**Local (no Azure)**: `uv sync && (cd frontend && npm ci) && uv run python scripts/dev.py`, then http://localhost:5173 with demo user `a1`.

**Azure, from scratch in any tenant** (details: [README § Deploy to Azure](README.md#deploy-to-azure), [infra/README.md](infra/README.md)):
1. **Ask the person to sign in**; you can't do it for them. `az login` and `azd auth login` must use the same account and tenant (`--tenant <id>` if they have several). The person needs: rights to create app registrations, and Owner (or Contributor + User Access Administrator) on the subscription. Never provision as a service principal; `preflight.py` refuses.
2. Ask for an environment name, subscription and region, then run without prompts:
   ```sh
   az account set --subscription <subscription-id>
   azd env new <env-name> --subscription <subscription-id> --location <region>
   azd up --no-prompt
   ```
   `azd up` runs: `preflight.py` (rights, model quota, fills deployer + IP) → Bicep (incl. Entra app registrations) → migrate, seed, map the deployer → deploy 3 services → `deploy_agent.py` → `verify_deployment.py` (endpoints, smoke, evals, App Insights trace). Takes ~15 min.
3. **Confirm success**: azd can hide hook output when run by an agent, so don't rely on the console. Run `uv run python scripts/verify_deployment.py` and require it to pass; report `azd env get-value FRONTEND_URL`.
4. Quota failure from preflight: `azd env set AZURE_AI_LOCATION <region-with-quota>` (or lower `AZURE_AI_MODEL_CAPACITY`), then `azd up --no-prompt` again. Postgres `SkuNotAvailable` during provision (region out of Burstable capacity; re-running doesn't help): `azd env set AZURE_POSTGRES_LOCATION <other-region>` (for example `centralus`), then `azd up --no-prompt`. Every step is idempotent; re-running is the fix for transient failures.
5. Optional CI: `uv run python scripts/setup_ci.py` (OIDC, Contributor only, needs a GitHub remote). CI deploys code and the agent; **infra changes (`infra/`, `azure.yaml`) still need `azd up` by a person**.
6. Code-only redeploy: `azd deploy` or `uv run python scripts/deploy_parallel.py`. Tear down: `azd down --purge`. It does not delete the 3 app registrations (tenant objects, not in the resource group); delete them with `az ad app delete --id` for `WEB_APP_ID`, `APP_API_APP_ID`, `ENERGY_SERVICE_APP_ID` (`azd env get-value <name>`).

## Layers (enforced by `tests/architecture/test_layers.py`)
- `application/` and `projections/` are framework-free: no FastAPI, MCP, Azure, OpenAI, psycopg or httpx imports.
- Only `app-api/.../orchestration/` talks to Foundry. Only `infrastructure/` touches the database.
- Adapters (`api/`, `mcp/`) are thin: parse, call the service, map errors.
- Wiring lives in `bootstrap.py`; nothing runs at import time; `main.create_app()` is the factory.

## Changing things
- **Tool change**: edit the MCP tool → `uv run python scripts/sync_tool_specs.py` → update `agent/instructions.md` if behaviour changed → add a golden question in `agent/evals/datasets/golden.jsonl`.
- **Agent output change**: update `shared/.../contracts/agent.py` and `agent/output-schema.json` together (contract-tested).
- **API contract change**: update `docs/technical-spec.md` and `frontend/src/types/api.ts`.
- **Infra change**: edit `infra/` → `bicep build infra/main.bicep` → `azd provision` (by a person) → update `infra/README.md`.
- Record every decision, change and fix in `docs/issues-changes-fixes.md` (newest first) and keep `docs/plan.md` current.

## Before you finish
```sh
uv run ruff check --fix . && uv run ruff format .
uv run mypy
uv run pytest
(cd frontend && npm run lint && npm test)
```
After an Azure deploy: `uv run python scripts/verify_deployment.py` must pass.
