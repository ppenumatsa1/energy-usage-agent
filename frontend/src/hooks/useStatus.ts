import { useEffect, useState } from "react";
import type { ApiClient } from "../api/client";
import type { StatusResponse } from "../types/api";

const REFRESH_MS = 60_000;

export type StatusState =
  | { status: "loading" }
  | { status: "ready"; data: StatusResponse }
  | { status: "error" };

/** Polls GET /api/status for the header health pills. */
export function useStatus(api: ApiClient): StatusState {
  const [state, setState] = useState<StatusState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .getStatus()
        .then((data) => !cancelled && setState({ status: "ready", data }))
        .catch(() => !cancelled && setState({ status: "error" }));
    void load();
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [api]);

  return state;
}
