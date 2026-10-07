import type {
  ChatRequest,
  ChatResponse,
  ConversationDetail,
  ConversationSummary,
  DevTokenResponse,
  DevUser,
  MeResponse,
  Problem,
  StatusEvent,
  StatusResponse,
} from "../types/api";
import { ApiError, NetworkError, StreamInterruptedError, isAbortError as isAbort, toApiError } from "./problems";
import { readSseStream } from "./sse";

export interface TokenSource {
  getToken(): Promise<string>;
  /** Called when the API answers 401 so the auth layer can re-authenticate. */
  onUnauthorized(): void;
}

export interface ChatOptions {
  onStatus?: (status: StatusEvent) => void;
  signal?: AbortSignal;
}

export interface ApiClient {
  getMe(): Promise<MeResponse>;
  chat(request: ChatRequest, options?: ChatOptions): Promise<ChatResponse>;
  chatJson(request: ChatRequest, options?: ChatOptions): Promise<ChatResponse>;
  chatStream(request: ChatRequest, options?: ChatOptions): Promise<ChatResponse>;
  listConversations(): Promise<ConversationSummary[]>;
  getConversation(conversationId: string): Promise<ConversationDetail>;
  getStatus(): Promise<StatusResponse>;
  deleteConversation(conversationId: string): Promise<void>;
}

/**
 * Signals that the response is not a stream at all (no SSE event was received),
 * so the caller may safely ask again for JSON.
 */
class StreamUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StreamUnavailableError";
  }
}

async function safeFetch(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(path, init);
  } catch (error) {
    if (isAbort(error, init.signal ?? undefined)) throw error;
    throw new NetworkError(error instanceof Error ? error.message : undefined);
  }
}

export function createApiClient(auth: TokenSource): ApiClient {
  async function request(path: string, init: RequestInit = {}): Promise<Response> {
    const token = await auth.getToken();
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    const response = await safeFetch(path, { ...init, headers });
    if (!response.ok) {
      const error = await toApiError(response);
      if (response.status === 401) auth.onUnauthorized();
      throw error;
    }
    return response;
  }

  async function getJson<T>(path: string): Promise<T> {
    const response = await request(path, { headers: { Accept: "application/json" } });
    return (await response.json()) as T;
  }

  async function chatJson(body: ChatRequest, options: ChatOptions = {}): Promise<ChatResponse> {
    const response = await request("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
      signal: options.signal,
    });
    return (await response.json()) as ChatResponse;
  }

  async function chatStream(body: ChatRequest, options: ChatOptions = {}): Promise<ChatResponse> {
    const response = await request("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal: options.signal,
    });
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      // Server chose not to stream; the body is already a ChatResponse.
      return (await response.json()) as ChatResponse;
    }
    if (!contentType.includes("text/event-stream") || !response.body) {
      throw new StreamUnavailableError(`Unexpected content type: ${contentType || "none"}`);
    }

    const correlationId = response.headers.get("x-correlation-id") ?? undefined;
    let result: ChatResponse | undefined;
    let problem: Problem | undefined;
    try {
      await readSseStream(response.body, (event) => {
        if (result || problem) return;
        try {
          if (event.event === "status") {
            options.onStatus?.(JSON.parse(event.data) as StatusEvent);
          } else if (event.event === "result") {
            result = JSON.parse(event.data) as ChatResponse;
          } else if (event.event === "error") {
            problem = JSON.parse(event.data) as Problem;
          }
        } catch {
          // Ignore a malformed event; a missing result is reported as an interrupted stream.
        }
      });
    } catch (error) {
      if (isAbort(error, options.signal)) throw error;
      // The server already accepted the question: report it, never resend automatically.
      if (!result && !problem) throw new StreamInterruptedError("Stream interrupted", correlationId);
    }

    if (problem) {
      const status = problem.status ?? 500;
      if (status === 401) auth.onUnauthorized();
      throw new ApiError(status, problem);
    }
    if (!result) throw new StreamInterruptedError("Stream ended without a result", correlationId);
    return result;
  }

  async function chat(body: ChatRequest, options: ChatOptions = {}): Promise<ChatResponse> {
    try {
      return await chatStream(body, options);
    } catch (error) {
      // Only a response that never was a stream falls back to JSON (once). Anything after the
      // server accepted the question (interrupted stream, network error, problem) is surfaced as-is.
      if (!(error instanceof StreamUnavailableError) || isAbort(error, options.signal)) throw error;
      return chatJson(body, options);
    }
  }

  return {
    getMe: () => getJson<MeResponse>("/api/me"),
    chat,
    chatJson,
    chatStream,
    listConversations: () => getJson<ConversationSummary[]>("/api/conversations"),
    getConversation: (conversationId: string) =>
      getJson<ConversationDetail>(`/api/conversations/${encodeURIComponent(conversationId)}`),
    getStatus: () => getJson<StatusResponse>("/api/status"),
    async deleteConversation(conversationId: string) {
      await request(`/api/conversations/${encodeURIComponent(conversationId)}`, { method: "DELETE" });
    },
  };
}

/** Dev-only endpoints used before a token exists (authMode "dev"). */
export async function getDevUsers(): Promise<DevUser[]> {
  const response = await safeFetch("/api/dev/users", { headers: { Accept: "application/json" } });
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as DevUser[];
}

export async function getDevToken(user: string): Promise<string> {
  const response = await safeFetch("/api/dev/token", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ user }),
  });
  if (!response.ok) throw await toApiError(response);
  const body = (await response.json()) as DevTokenResponse;
  return body.accessToken;
}
