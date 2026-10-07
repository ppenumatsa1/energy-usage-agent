import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiClient } from "../api/client";
import { describeError, type ErrorInfo } from "../api/problems";
import type { ConversationSummary } from "../types/api";

export function useConversations(api: ApiClient) {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<ErrorInfo | null>(null);
  const [version, setVersion] = useState(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .listConversations()
      .then((list) => {
        if (cancelled) return;
        setItems(Array.isArray(list) ? list : []);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(describeError(err));
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [api, version]);

  const refresh = useCallback(() => setVersion((n) => n + 1), []);

  /** Removes a conversation from the list without calling the API (e.g. after a 404). */
  const drop = useCallback(
    (conversationId: string) => setItems((list) => list.filter((c) => c.conversationId !== conversationId)),
    [],
  );

  const remove = useCallback(
    async (conversationId: string) => {
      try {
        await api.deleteConversation(conversationId);
        if (!mounted.current) return;
        drop(conversationId);
        setError(null);
      } catch (err) {
        if (mounted.current) setError(describeError(err));
      }
    },
    [api, drop],
  );

  return { items, loaded, error, refresh, drop, remove };
}
