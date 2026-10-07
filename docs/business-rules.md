# Business Rules – energy-usage-agent (v0.3)

> This is the single source for the rules. Other docs link here instead of repeating them.
> **[OPEN]** marks values still to be confirmed.

## Customer scoping and onboarding
- **BR-1 Customer comes from identity only.**
  - The customer is resolved from the token claims `(tid, oid)` through the `user_customer` mapping.
  - It is never taken from user text, tool arguments, request parameters or the LLM.
  - No REST route, MCP tool or agent tool accepts `customer_id`, `tenant_id`, `tid` or `oid`.
- **BR-2 Onboarding.**
  - A user with no mapping is "not onboarded": no data access and a friendly message.
  - For the POC, admins add mappings by script.
- **BR-3 Enforcement in two places.**
  - The energy service sets the customer scope for every DB transaction.
  - Postgres row-level security enforces the same scope even if the code is wrong.
  - Prompt instructions are **not** a security control.

## Time and date resolution
- **BR-4 Customer time zone.**
  - Each customer has an IANA time zone.
  - Relative periods ("today", "this month", "last week") resolve **on the server** in that time zone. Weeks start on Monday **[OPEN]**.
  - "This month" = month start → now (month-to-date).
- **BR-5 State assumptions.** Every answer lists the resolved period(s) and time zone in `assumptions`.
- **BR-6 Comparisons.** Period comparisons compare like-for-like lengths. "This month vs last month" during the month compares month-to-date with the same number of days of the previous month, and says so **[OPEN]**: confirm vs. full last month.

## Range and granularity limits
- **BR-7 Limits.**
  - `end > start`.
  - Maximum range 13 months. Longer requests are capped, and the answer says so.
  - Hourly granularity only for ranges ≤ 31 days. Hours are local; on the day clocks go back the repeated hour is shown twice with its zone (e.g. `01:00 CDT`, `01:00 CST`), so that day has 25 hours and the spring-forward day 23.
  - 15-minute granularity is not exposed in the POC **[OPEN]**.
  - Top-N ≤ 10.
  - At most 5 tool rounds per user turn (one round may run several tools).

## Numbers and sources
- **BR-8 Numbers come from tools.**
  - Every number shown in the table or chart comes from a tool result.
  - The agent's text may only restate tool values. It never estimates or invents them.

## Data completeness
- **BR-10 Missing data.**
  - No data for a range: say so and show no chart.
  - Partial data: show what exists and list the missing days or periods (from coverage).

## Domain and refusals
- **BR-9 Scope.**
  - Only energy-usage questions are answered.
  - Cost/tariff, other customers' data and non-energy topics are politely declined, with suggested questions.
  - Ambiguous requests get a clarifying question.

## Conversations and usage
- **BR-11 Conversation ownership.**
  - A conversation belongs to the `(tid, oid)` that created it.
  - Any other user gets "not found".
- **BR-14 Conversation history.**
  - Each turn (question, answer, table, chart, assumptions, trace) is stored in the app-api database so a reopened conversation looks exactly as it did.
  - Kept 30 days after the last activity (`HISTORY_RETENTION_DAYS`); after that it can't be opened or continued and is deleted by a background job. Deleting a conversation deletes its turns at once.
  - Only the owner can read it (BR-11). History is not a log: BR-12 still applies to audit logs.
- **BR-13 Rate limit.** Per user (`tid:oid`), for example 20 requests/min **[OPEN]**.

## Audit
- **BR-12 Audit every tool call.**
  - Log: `tid`, `oid`, `customer_id`, tool, validated parameters, row count, latency, outcome, correlation ID.
  - Never log prompts, model output, tokens or raw result rows.
