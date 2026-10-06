import type { ChatStatus, Trace } from "../types/api";

export type Tone = "ok" | "warn" | "info" | "neutral" | "error";

export const STATUS_META: Record<ChatStatus, { label: string; tone: Tone }> = {
  ok: { label: "Answered", tone: "ok" },
  no_data: { label: "No data", tone: "warn" },
  clarify: { label: "Needs detail", tone: "info" },
  refused: { label: "Out of scope", tone: "neutral" },
  error: { label: "Error", tone: "error" },
};

export function agentLabel(trace: Trace | undefined): string {
  if (!trace) return "Agent";
  if (trace.agent === "fake") return "Fake agent";
  return trace.agentName || "Foundry agent";
}
