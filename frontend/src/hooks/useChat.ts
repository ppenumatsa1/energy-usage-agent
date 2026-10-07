import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiClient } from "../api/client";
import { ApiError, StreamInterruptedError, describeError, isAbortError, type ErrorInfo } from "../api/problems";
import type { ChatResponse, ConversationDetail, StatusEvent } from "../types/api";

export type TurnError = ErrorInfo;

export interface ChatTurn {
  id: string;
  question: string;
  state: "pending" | "done" | "error";
  /** Epoch ms when the request started (live turns only). */
  startedAt?: number;
  stage?: StatusEvent;
  response?: ChatResponse;
  error?: TurnError;
}

export type HistoryState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string; notFound: boolean; correlationId?: string };

export interface ChatCallbacks {
  /** Called after every answer that was saved to a conversation. */
  onAnswered?: (conversationId: string) => void;
  /** Called when a conversation turns out to be gone (404 conversation_not_found). */
  onMissing?: (conversationId: string) => void;
  /** Called when a stream broke after the server accepted the question; the answer may still have been saved. */
  onInterrupted?: () => void;
}

const NOT_FOUND_MESSAGE =
  "This conversation is no longer available. It may have been deleted or passed the history retention period.";

let turnCounter = 0;
const nextTurnId = () => `turn-${Date.now()}-${++turnCounter}`;

function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && (error.code === "conversation_not_found" || error.status === 404);
}

function historyTurns(detail: ConversationDetail): ChatTurn[] {
  return (detail.turns ?? []).map((t, i) => ({
    id: `${detail.conversationId}-${i}`,
    question: t.question,
    state: "done",
    response: t.response,
  }));
}

export function useChat(api: ApiClient, { onAnswered, onMissing, onInterrupted }: ChatCallbacks = {}) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [title, setTitle] = useState<string | undefined>();
  const [history, setHistory] = useState<HistoryState>({ status: "idle" });
  /** True when an opened conversation exists but has no stored turns (created before history was kept). */
  const [historyMissing, setHistoryMissing] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const conversationRef = useRef<string | undefined>(undefined);
  const loadRef = useRef(0);

  useEffect(
    () => () => {
      // Cancel in-flight work so nothing sets state after unmount.
      abortRef.current?.abort();
      loadRef.current += 1;
    },
    [],
  );

  const updateTurn = (id: string, patch: Partial<ChatTurn>) =>
    setTurns((list) => list.map((t) => (t.id === id ? { ...t, ...patch } : t)));

  const setConversation = (id: string | undefined) => {
    conversationRef.current = id;
    setConversationId(id);
  };

  const reset = useCallback((id: string | undefined) => {
    abortRef.current?.abort();
    abortRef.current = null;
    loadRef.current += 1;
    conversationRef.current = id;
    setConversationId(id);
    setTurns([]);
    setTitle(undefined);
    setHistoryMissing(false);
  }, []);

  const run = useCallback(
    async (turnId: string, question: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const previousConversation = conversationRef.current;
      try {
        const response = await api.chat(
          { message: question, ...(previousConversation ? { conversationId: previousConversation } : {}) },
          {
            signal: controller.signal,
            onStatus: (stage) => updateTurn(turnId, { stage }),
          },
        );
        if (controller.signal.aborted) return;
        updateTurn(turnId, { state: "done", response });
        if (response.conversationId) {
          setConversation(response.conversationId);
          onAnswered?.(response.conversationId);
        }
      } catch (error) {
        if (isAbortError(error, controller.signal)) return;
        const apiError = error instanceof ApiError ? error : undefined;
        if (apiError?.code === "conversation_not_found") {
          if (previousConversation) onMissing?.(previousConversation);
          setConversation(undefined);
        }
        if (error instanceof StreamInterruptedError) onInterrupted?.();
        updateTurn(turnId, { state: "error", error: describeError(error) });
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
      }
    },
    [api, onAnswered, onMissing, onInterrupted],
  );

  const send = useCallback(
    (message: string) => {
      const question = message.trim();
      if (!question) return;
      const id = nextTurnId();
      setHistory((h) => (h.status === "error" ? { status: "idle" } : h));
      setTurns((list) => [...list, { id, question, state: "pending", startedAt: Date.now() }]);
      void run(id, question);
    },
    [run],
  );

  const retry = useCallback(
    (turnId: string) => {
      const turn = turns.find((t) => t.id === turnId);
      if (!turn) return;
      updateTurn(turnId, {
        state: "pending",
        startedAt: Date.now(),
        error: undefined,
        response: undefined,
        stage: undefined,
      });
      void run(turnId, turn.question);
    },
    [run, turns],
  );

  const newChat = useCallback(() => {
    reset(undefined);
    setHistory({ status: "idle" });
  }, [reset]);

  const openConversation = useCallback(
    (id: string) => {
      reset(id);
      setHistory({ status: "loading" });
      const token = loadRef.current;
      api
        .getConversation(id)
        .then((detail) => {
          if (token !== loadRef.current) return;
          const loaded = historyTurns(detail);
          setTurns(loaded);
          setHistoryMissing(loaded.length === 0);
          setTitle(detail.title || undefined);
          setHistory({ status: "idle" });
        })
        .catch((error: unknown) => {
          if (token !== loadRef.current) return;
          const notFound = isNotFound(error);
          if (notFound) {
            setConversation(undefined);
            onMissing?.(id);
          }
          const info = describeError(error);
          setHistory({
            status: "error",
            notFound,
            message: notFound ? NOT_FOUND_MESSAGE : info.message,
            correlationId: info.correlationId,
          });
        });
    },
    [api, onMissing, reset],
  );

  const isBusy = history.status === "loading" || turns.some((t) => t.state === "pending");

  return { turns, conversationId, title, history, historyMissing, isBusy, send, retry, newChat, openConversation };
}
