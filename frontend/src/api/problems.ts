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

/** Raised when the network request itself fails before any response (offline, DNS, CORS). */
export class NetworkError extends Error {
  readonly code = "network_error";

  constructor(message = "Network request failed") {
    super(message);
    this.name = "NetworkError";
  }
}

/**
 * Raised when a chat stream breaks after the server accepted the question.
 * The turn may have completed server-side, so the client must not resend it automatically.
 */
export class StreamInterruptedError extends Error {
  readonly code = "stream_interrupted";
  readonly correlationId?: string;

  constructor(message = "Stream interrupted", correlationId?: string) {
    super(message);
    this.name = "StreamInterruptedError";
    this.correlationId = correlationId;
  }
}

const GENERIC_MESSAGE = "Something went wrong. Please try again.";
export const OFFLINE_MESSAGE =
  "You appear to be offline or we can't reach the service. Check your connection and try again.";
export const STREAM_INTERRUPTED_MESSAGE =
  "The connection dropped before the answer arrived. Your question may still have been answered — check History or try again.";

/** Problem codes where sending the same request again can't succeed. */
const NOT_RETRYABLE = new Set(["not_onboarded", "invalid_request", "conversation_not_found", "unauthorized"]);

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
    case "internal_error":
      return GENERIC_MESSAGE;
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
  if (error instanceof NetworkError) return OFFLINE_MESSAGE;
  if (error instanceof StreamInterruptedError) return STREAM_INTERRUPTED_MESSAGE;
  return GENERIC_MESSAGE;
}

/** What the UI shows for a failed request. */
export interface ErrorInfo {
  message: string;
  code?: string;
  correlationId?: string;
  /** True when sending the same request again may succeed (offered as an explicit "Try again"). */
  retryable: boolean;
  retryAfterSeconds?: number;
}

export function describeError(error: unknown): ErrorInfo {
  const message = errorMessage(error);
  if (error instanceof ApiError) {
    const code = error.code;
    const retryable = !(code && NOT_RETRYABLE.has(code)) && ![400, 401, 403, 404, 422].includes(error.status);
    return {
      message,
      code,
      correlationId: error.correlationId,
      retryable,
      retryAfterSeconds: error.retryAfterSeconds,
    };
  }
  if (error instanceof StreamInterruptedError) {
    return { message, code: error.code, correlationId: error.correlationId, retryable: true };
  }
  if (error instanceof NetworkError) return { message, code: error.code, retryable: true };
  return { message, retryable: true };
}

/** True for user-initiated cancellation (new question, navigation), which is never shown as an error. */
export function isAbortError(error: unknown, signal?: AbortSignal | null): boolean {
  return Boolean(signal?.aborted) || (error instanceof DOMException && error.name === "AbortError");
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
