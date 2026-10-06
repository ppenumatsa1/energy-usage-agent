import { vi } from "vitest";
import type { ChatResponse, StatusResponse } from "../../src/types/api";

export const sampleResponse: ChatResponse = {
  answer: "You used 1,234.57 kWh so far this month.\nThat's 5% more than the same days last month.",
  status: "ok",
  table: {
    columns: [
      { key: "period", label: "Period", type: "string" },
      { key: "kwh", label: "Usage", type: "number" },
    ],
    rows: [
      { period: "2026-10-01", kwh: 400.123 },
      { period: "2026-10-02", kwh: 834.4467 },
    ],
    unit: "kWh",
  },
  chart: { type: "bar", x: "period", y: ["kwh"], title: "Daily usage" },
  assumptions: ["this month = Oct 1–2, 2026 (America/Chicago)"],
  conversationId: "conv-1",
  correlationId: "corr-123",
  createdAt: "2026-10-02T15:04:05Z",
  trace: {
    agent: "fake",
    agentName: "energy-usage-agent",
    durationMs: 1234,
    steps: [
      {
        tool: "get_usage",
        arguments: { start: "this_month", end: "this_month", granularity: "day" },
        status: "ok",
        rows: 2,
        errorCode: null,
        durationMs: 57,
      },
    ],
    checks: [
      { name: "Signed-in scope", detail: "Tools only see your own sites and meters.", outcome: "pass" },
      { name: "Numbers from tools", detail: "Values come straight from tool results.", outcome: "pass" },
      { name: "Energy topics only", detail: "Question is about energy usage.", outcome: "info" },
    ],
  },
};

export const sampleStatus: StatusResponse = {
  components: [
    { id: "api", label: "API", status: "ok", detail: "app-api" },
    { id: "energy", label: "Energy data", status: "ok", detail: "energy-service" },
    { id: "database", label: "History", status: "down", detail: "Database unreachable" },
    { id: "agent", label: "Agent", status: "ok", detail: "Fake agent" },
  ],
  historyRetentionDays: 30,
};

export function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers as Record<string, string> | undefined) },
  });
}

export function problemResponse(status: number, code: string, extra: Record<string, unknown> = {}): Response {
  return new Response(
    JSON.stringify({ type: "about:blank", title: code, status, detail: code, code, correlationId: "corr-err", ...extra }),
    { status, headers: { "Content-Type": "application/problem+json" } },
  );
}

/** Builds a streaming SSE response whose body is delivered in the given chunks. */
export function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;

/** Installs a fetch mock routed by "METHOD /path". Returns the mock for call assertions. */
export function mockFetch(routes: Record<string, Handler>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
    const method = (init.method ?? "GET").toUpperCase();
    const handler = routes[`${method} ${url}`];
    if (!handler) return new Response("not found", { status: 404 });
    return handler(url, init);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}
