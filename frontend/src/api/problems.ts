import type { Problem } from "../types/api";

export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem;
  readonly retryAfterSeconds?: number;

  constructor(status: number, problem: Problem, retryAfterSeconds?: number) {
    super(problem.detail || problem.title || `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
    this.retryAfterSeconds = retryAfterSeconds;
  }

  get code(): string | undefined {
    return this.problem.code;
  }

  get correlationId(): string | undefined {
    return this.problem.correlationId;
  }
}

/** Raised when the network request itself fails (offline, DNS, CORS, aborted stream). */
export class NetworkError extends Error {
  constructor(message = "Network request failed") {
    super(message);
    this.name = "NetworkError";
  }
}

const GENERIC_MESSAGE = "Something went wrong. Please try again.";

export function problemMessage(problem: Problem, retryAfterSeconds?: number): string {
  switch (problem.code) {
    case "not_onboarded":
      return "Your account isn't set up yet. Contact your administrator.";
    case "rate_limited":
      return retryAfterSeconds && retryAfterSeconds > 0
        ? `You're asking quickly — try again in ${retryAfterSeconds} seconds.`
        : "You're asking quickly — try again in a few seconds.";
    case "invalid_request":
      return "I couldn't process that question. Please rephrase it and try again.";
    case "upstream_unavailable":
      return "The usage service is temporarily unavailable. Please try again in a moment.";
    case "conversation_not_found":
      return "This conversation is no longer available. Start a new chat to continue.";
    case "unauthorized":
      return "Your session has expired. Signing you in again…";
    default:
      break;
  }
  switch (problem.status) {
    case 401:
      return "Your session has expired. Signing you in again…";
    case 403:
      return "You don't have access to this data.";
    case 404:
      return "We couldn't find what you were looking for.";
    case 429:
      return "You're asking quickly — try again in a few seconds.";
    case 502:
    case 503:
    case 504:
      return "The usage service is temporarily unavailable. Please try again in a moment.";
    default:
      return GENERIC_MESSAGE;
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return problemMessage(error.problem, error.retryAfterSeconds);
  if (error instanceof NetworkError) {
    return "We couldn't reach the server. Check your connection and try again.";
  }
  return GENERIC_MESSAGE;
}

function parseRetryAfter(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds)) return Math.max(0, Math.ceil(seconds));
  const date = Date.parse(value);
  if (Number.isNaN(date)) return undefined;
  return Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

/** Builds an ApiError from a non-OK response, reading an application/problem+json body if present. */
export async function toApiError(response: Response): Promise<ApiError> {
  let problem: Problem = { status: response.status };
  try {
    const text = await response.text();
    if (text) {
      const parsed: unknown = JSON.parse(text);
      if (parsed && typeof parsed === "object") problem = { status: response.status, ...(parsed as Problem) };
    }
  } catch {
    // Body was not JSON; keep the status-only problem.
  }
  if (!problem.correlationId) {
    const header = response.headers.get("x-correlation-id");
    if (header) problem.correlationId = header;
  }
  return new ApiError(response.status, problem, parseRetryAfter(response.headers.get("retry-after")));
}
