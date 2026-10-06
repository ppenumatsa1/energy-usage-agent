import type { CellValue, ColumnType } from "../types/api";

const numberFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

export function formatNumber(value: number): string {
  return Number.isFinite(value) ? numberFormat.format(value) : String(value);
}

export function formatCell(value: CellValue | undefined, type: ColumnType): string {
  if (value === null || value === undefined || value === "") return "—";
  if (type === "number") {
    const n = typeof value === "number" ? value : Number(value);
    return Number.isNaN(n) ? String(value) : formatNumber(n);
  }
  return String(value);
}

/** "320 ms", "1.2 s", "12 s". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1000;
  return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`;
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${formatNumber(count)} ${count === 1 ? one : many}`;
}

/** "just now", "5m ago", "2h ago", "3d ago", then a short date. */
export function relativeTime(value: string | undefined, now = Date.now()): string {
  if (!value) return "";
  const time = new Date(value).getTime();
  if (Number.isNaN(time)) return value;
  const minutes = Math.floor((now - time) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(time).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function formatTimestamp(value: string | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
