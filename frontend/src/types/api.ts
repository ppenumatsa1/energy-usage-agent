export interface MeResponse {
  onboarded: boolean;
  customerName: string | null;
  timezone: string | null;
  userName: string | null;
}

export type ColumnType = "string" | "number" | "date";

export interface TableColumn {
  key: string;
  label: string;
  type: ColumnType;
}

export type CellValue = string | number | null;
export type TableRow = Record<string, CellValue>;

export interface ResultTableData {
  columns: TableColumn[];
  rows: TableRow[];
  unit: string;
}

export interface ChartSpec {
  type: "line" | "bar";
  x: string;
  y: string[];
  title: string;
}

export type ChatStatus = "ok" | "no_data" | "clarify" | "refused" | "error";

/** One tool call the agent made during a turn (no result rows; those are in `table`). */
export interface TraceStep {
  tool: string;
  arguments: Record<string, unknown>;
  status: "ok" | "error";
  rows: number | null;
  errorCode: string | null;
  durationMs: number;
  resultId?: string | null;
  assumptions?: string[];
  summary?: Record<string, unknown>;
  errorMessage?: string | null;
}

/** A guardrail / data-integrity check applied to the turn, e.g. "Numbers from tools". */
export interface TraceCheck {
  name: string;
  detail: string;
  outcome: "pass" | "info" | "blocked";
}

/** "How this was answered": present on every ChatResponse (live and from history). */
export interface Trace {
  agent: "fake" | "foundry";
  agentName: string;
  durationMs: number;
  steps: TraceStep[];
  checks: TraceCheck[];
  resultIds?: string[];
}

export interface ChatResponse {
  answer: string;
  status: ChatStatus;
  table: ResultTableData | null;
  chart: ChartSpec | null;
  assumptions: string[];
  conversationId: string;
  correlationId: string;
  /** ISO timestamp of when the answer was produced. */
  createdAt: string;
  trace: Trace;
}

export interface ChatRequest {
  message: string;
  conversationId?: string;
}

export type ChatStage = "thinking" | "tool" | "composing";

export interface StatusEvent {
  stage: ChatStage;
  tool?: string;
}

export interface ConversationSummary {
  conversationId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  turnCount: number;
}

export interface ConversationTurn {
  question: string;
  response: ChatResponse;
}

/** GET /api/conversations/{id}: full stored history (kept 30 days). 404 conversation_not_found if not yours. */
export interface ConversationDetail {
  conversationId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  turns: ConversationTurn[];
}

/** GET /api/status (signed-in): health pills for the header. */
export interface StatusComponent {
  id: "api" | "energy" | "database" | "agent";
  label: string;
  status: "ok" | "down";
  detail: string;
}

export interface StatusResponse {
  components: StatusComponent[];
  historyRetentionDays: number;
}

export type ProblemCode =
  | "not_onboarded"
  | "rate_limited"
  | "invalid_request"
  | "upstream_unavailable"
  | "conversation_not_found"
  | "unauthorized";

export interface Problem {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  code?: ProblemCode | string;
  correlationId?: string;
}

export interface DevUser {
  id: string;
  label: string;
}

export interface DevTokenResponse {
  accessToken: string;
}
