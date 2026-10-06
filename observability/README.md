# Observability

Both services send OpenTelemetry data to one workspace-based Application Insights resource (`APPLICATIONINSIGHTS_CONNECTION_STRING`). Container console and system logs go to the Log Analytics workspace that backs the Container Apps environment.

## What to look at
| Question | Where |
|---|---|
| Is one chat turn one connected trace (web → app-api → energy-service → Postgres)? | `kql/trace-completeness.kql`, then App Insights **Transaction search** on a sample `operation_Id` |
| Are users denied, and why (audience, scope, tenant, not onboarded)? | `kql/authz-denials.kql` |
| Which tools are slow or failing? | `kql/tool-latency.kql` |
| Is a service failing at all? | App Insights **Failures** and **Performance**, filtered by role (`app-api`, `energy-service`) |
| Did a container crash or fail its probe? | Log Analytics: `ContainerAppSystemLogs_CL` / `ContainerAppConsoleLogs_CL` (or the newer `ContainerAppSystemLogs` / `ContainerAppConsoleLogs`) |
| Is the model throttling? | Foundry account **Metrics** (requests, 429s, token usage) |

## Assumptions the queries make
- Queries use the App Insights table names (`requests`, `dependencies`, `traces`) and `customDimensions`. In Log Analytics directly, the tables are `AppRequests`, `AppDependencies` and `AppTraces`, and the column is `Properties`.
- `cloud_RoleName` is the OpenTelemetry `service.name`, `app-api` or `energy-service`. Change the `let` values if the services use different names.
- Audit events are log records (`traces`) with:
  - `customDimensions.event == "tool_call"` and `tool`, `outcome`, `latency_ms`, `row_count`, `correlation_id`;
  - `customDimensions.event == "authz_denied"` and `reason`.
- `tool-latency.kql` counts any `outcome` other than `ok`/`success` as a failure.

## Privacy
- Prompts, answers and result rows are never logged. Audit events carry only IDs, names, counts and timings.
- Don't paste query results containing user or tenant IDs into issues, docs or chat.

## How to run
App Insights resource → **Logs** → paste a file and run it. Each file is one query; extra variants are in comments at the top of the main query.
