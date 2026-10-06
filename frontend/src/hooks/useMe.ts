import { useCallback, useEffect, useState } from "react";
import type { ApiClient } from "../api/client";
import { ApiError } from "../api/problems";
import type { MeResponse } from "../types/api";

export type MeState =
  | { status: "loading" }
  | { status: "ready"; me: MeResponse }
  | { status: "not_onboarded"; me: MeResponse | null }
  | { status: "error"; error: unknown };

export function useMe(api: ApiClient): { state: MeState; reload: () => void } {
  const [state, setState] = useState<MeState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api
      .getMe()
      .then((me) => {
        if (cancelled) return;
        setState(me.onboarded ? { status: "ready", me } : { status: "not_onboarded", me });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.code === "not_onboarded") {
          setState({ status: "not_onboarded", me: null });
        } else {
          setState({ status: "error", error });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [api, attempt]);

  const reload = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((n) => n + 1);
  }, []);

  return { state, reload };
}
