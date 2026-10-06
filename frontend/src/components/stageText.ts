import type { StatusEvent } from "../types/api";

const TOOL_TEXT: Record<string, string> = {
  get_usage: "Looking up usage…",
  compare_usage: "Comparing periods…",
  get_peak_usage: "Finding peak usage…",
  get_usage_breakdown: "Breaking down usage by site or meter…",
  list_sites_and_meters: "Checking your sites and meters…",
  get_data_coverage: "Checking data coverage…",
};

export const DEFAULT_STAGE_TEXT = "Looking up your usage…";

export function stageText(status?: StatusEvent): string {
  if (!status) return DEFAULT_STAGE_TEXT;
  switch (status.stage) {
    case "thinking":
      return DEFAULT_STAGE_TEXT;
    case "tool":
      return (status.tool && TOOL_TEXT[status.tool]) || DEFAULT_STAGE_TEXT;
    case "composing":
      return "Writing the answer…";
    default:
      return DEFAULT_STAGE_TEXT;
  }
}
