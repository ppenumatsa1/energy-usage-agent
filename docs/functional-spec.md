# Functional Spec – energy-usage-agent (v0.3)

> Status: Draft for review. **[OPEN]** marks items that still need a decision.
> Related: [userflow](userflow.md) · [business rules](business-rules.md) · [technical spec](technical-spec.md) · [architecture](architecture.md)

## 1. Goal
Users sign in and ask questions about their energy usage in plain English. They see the result as a short answer, a table and, where useful, a chart.

## 2. Actors
| Actor | Description |
|---|---|
| Customer user | Signs in with their work account: a member or invited guest of the app's Entra tenant. Sees only their own customer's data. |
| Admin (operator) | Maps users to customer accounts. For the POC this is a seed/SQL script, not an admin UI. **[OPEN]** confirm. |

## 3. Core functions
| ID | Function | Rule / flow reference |
|---|---|---|
| F1 | Sign in with work account (Entra ID, single tenant + guests) | [userflow §2](userflow.md#2-journey) |
| F2 | Identify the authenticated customer | [BR-1, BR-2](business-rules.md#customer-scoping-and-onboarding) |
| F3 | Ask a natural-language question | [userflow §2](userflow.md#2-journey) |
| F4 | Agent determines intent and query parameters | [technical spec §6](technical-spec.md#6-agent-foundry-prompt-agent) |
| F5 | Agent requests tools; tools are served over MCP | [architecture: chat turn](architecture.md#chat-turn) |
| F6 | Energy service returns only the caller's authorized data | [BR-1](business-rules.md#customer-scoping-and-onboarding) |
| F7 | Render a short answer, a table, and a chart when useful | [§5](#5-response-contract) |
| F8 | Follow-up questions keep the conversation context | [userflow §4](userflow.md#4-follow-up-questions) |
| F9 | Handle invalid ranges, missing data and authorization failures | [userflow §5](userflow.md#5-error-and-edge-case-ux) |

## 4. Supported question types (POC)
| Intent | Example | Output |
|---|---|---|
| Usage over a period | "Show my usage this month." | Total kWh + daily table + bar/line chart |
| Period comparison | "Compare this month vs last month." | Totals, delta and % change; table; grouped bar chart |
| Peak / min | "What day had the highest usage?" | Day and value; top-N table; chart with the peak highlighted |
| Breakdown | "Usage by site last week" / "Which meter used the most?" | Table + stacked bar chart |
| Filter by site/meter | "Show usage for the Austin site this month" | Same as usage over a period, filtered |

The data has 15-minute interval reads and multiple sites and meters per customer. Cost and tariff questions are out of scope ([BR-9](business-rules.md#domain-and-refusals)).

## 5. Response contract
What the UI receives for each answer:
- `answer`: 1–3 sentence summary
- `table`: columns + rows, built **only from tool results** ([BR-8](business-rules.md#numbers-and-sources))
- `chart` (optional): type (line/bar/grouped-bar/stacked-bar), x, y, series; references table columns
- `assumptions`: for example "this month = Oct 1–6, 2026 (America/Chicago)"
- `conversationId`, `correlationId`

## 6. Non-functional requirements (POC targets)
- **Security:** customer isolation enforced in the energy service and the DB (RLS). Least-privilege identities. User tokens never leave our services.
- **Latency:** first token in under 3 s and full answer in under 10 s for typical questions **[OPEN]**.
- **Auditability:** every tool call is logged ([BR-12](business-rules.md#audit)).
- **Accessibility:** tables are readable without the chart.

## 7. Out of scope (POC)
- Writing or changing any energy data
- Billing, payments, cost/tariff questions
- Mobile apps
- APIM (optional later)
- Admin UI for user mapping

## 8. Acceptance criteria
1. A user from tenant A cannot get tenant B's data through any prompt, tool parameter or API call (negative tests).
2. Each core sample question returns a correct answer, table and chart against the seed data.
3. A follow-up question ("and last month?") resolves correctly using context.
4. Each case in [userflow §5](userflow.md#5-error-and-edge-case-ux) shows the specified behavior.
5. A full request trace is visible in App Insights from the UI through to the DB query.
