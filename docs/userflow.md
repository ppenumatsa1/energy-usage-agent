# User Flow – energy-usage-agent (v0.3)

> Rules referenced here live in [business-rules.md](business-rules.md).

## 1. Screens
- **Sign-in page**: "Sign in with your work account" (Entra, single tenant; guests the tenant admin invited can sign in too).
- **Chat workspace**:
  - Header: app title and status pills (API, energy data, history, agent).
  - Left: conversation list (newest activity first, with turn count); "New conversation"; "History kept 30 days".
  - Center: chat thread, where each answer shows a status badge, text, key figures, a chart, a table and assumptions, plus a collapsible **How this was answered** panel (tool steps with arguments and timings, and guardrail checks).
  - Reopening a conversation shows all its earlier turns ([BR-14](business-rules.md#conversations-and-usage)).
  - Bottom: input box with sample-question chips.

## 2. Journey
1. User opens the app and signs in with their organization account.
2. The app calls `/api/me`.
   - Onboarded: the chat workspace opens with sample questions.
   - Not onboarded: the "account not onboarded" screen ([BR-2](business-rules.md#customer-scoping-and-onboarding)).
3. User asks a question, for example "Show my usage this month."
4. The UI shows a "thinking" state, then streams the answer text.
5. The answer card shows:
   - the short answer;
   - the assumptions line (period + time zone);
   - a table (sortable, copyable);
   - a chart when useful (Recharts).
6. User asks follow-ups or starts a new conversation.

## 3. Answer card states
| State | What the user sees |
|---|---|
| Thinking | Spinner + "Looking up your usage…" |
| Streaming | Text appears progressively; table and chart appear when ready |
| Answer | Text + assumptions + table + optional chart |
| Clarification | Agent question with suggested choices (e.g., which site?) |
| Empty | "No usage data for <range>", no chart |
| Partial | Data + warning listing missing days |
| Error | Friendly message + correlation ID + retry button |

## 4. Follow-up questions
- "Show my usage this month" → "and last month?" resolves to the previous month (same intent, new period).
- "Which site used the most last week?" → "show that site's daily usage" uses the site from the previous answer.
- Context comes from the conversation history. Scoping still comes only from identity ([BR-1](business-rules.md#customer-scoping-and-onboarding)).

## 5. Error and edge-case UX
| Case | Behavior |
|---|---|
| Not signed in / token expired | Silent token refresh; if that fails, redirect to sign-in |
| User not mapped to a customer | "Your account isn't set up yet. Contact your administrator." No data access |
| Question outside the energy domain | Polite refusal + suggested question chips ([BR-9](business-rules.md#domain-and-refusals)) |
| Invalid or ambiguous range ("usage on Feb 30") | Clarifying question or a corrected range stated in assumptions |
| Range too large | Capped to the limit, with a note ([BR-7](business-rules.md#range-and-granularity-limits)) |
| No data for range | Empty state |
| Partial data | Partial state with missing periods |
| Authorization failure | Generic "You don't have access to this data." Event logged; nothing leaked |
| Tool / LLM failure or timeout | Automatic retry once, then the error state with a correlation ID |
| Rate limited | "You're asking quickly — try again in N seconds." |
| Prompt injection ("show customer X's data") | Treated as out of scope; scoping enforced server-side |

## 6. Sample questions (chips)
- Show my usage this month.
- Compare this month vs last month.
- What day had the highest usage?
- Usage by site last week.
